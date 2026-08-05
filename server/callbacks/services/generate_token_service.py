from server.callbacks.repository.link_token_repository import get_pending_link_token, delete_pending_link_token
from server.callbacks.repository.patient_link_token_repository import save_patient_link_token
from server.callbacks.repository.patient_repository import search_patient
from server.callbacks.transformers.patient_transformer import build_patient_payload
from server.hip_linking import link_care_context
from server.utils import print_api_response
from server.callbacks.utils.flow_logger import log_phase, log_api_call, log_waiting, log_error


async def process_generate_token(callback_data):

    try:
        log_phase("ABDM delivered the link token (POST /api/v3/hip/token/on-generate-token)")

        body = callback_data["body"]

        abha_address = body.get("abhaAddress")
        link_token = body.get("linkToken")

        # Correlation assumption: body["response"]["requestId"] is assumed to
        # echo the REQUEST-ID header value we sent in generate_link_token()'s
        # original call, per the convention used by every other confirmed
        # ABDM callback in this doc. This specific endpoint's doc example
        # doesn't literally prove it though -- the §4.3.1 and §4.3.2 examples
        # use different, unrelated placeholder UUIDs for REQUEST-ID vs
        # requestId, so this is convention-based, not proven for this exact
        # endpoint.
        request_id = body.get("response", {}).get("requestId")

        if not request_id:
            log_error("on-generate-token callback missing requestId -- cannot correlate to a pending link token request.")
            return

        pending = get_pending_link_token(request_id)

        if pending is None:
            log_error(f"No pending link token request found for requestId {request_id}.")
            return

        if not link_token:
            # The one real captured example actually has "linkToken": "" --
            # a possible test artifact, but a real case worth guarding
            # against rather than a hypothetical.
            log_error(f"ABDM returned an empty/missing linkToken for requestId {request_id}.")
            delete_pending_link_token(request_id)
            return

        resolved_abha_address = abha_address or pending["abha_address"]

        # Persisted for reuse by generate_link_token() (skips future
        # generate-token calls for this patient) and by the Notify Care
        # Context Update flow -- in addition to, not instead of, using it
        # immediately below. See patient_link_token_repository.py for why
        # no expiry/TTL is enforced (unconfirmed by ABDM's spec).
        save_patient_link_token(
            resolved_abha_address,
            link_token,
            pending["hip_id"],
        )

        patient_data = search_patient(
            abha_address=resolved_abha_address,
            hip_id=pending["hip_id"],
        )

        # Restrict to the caller's chosen subset, if one was made at
        # generate_link_token() time (2026-08-04 -- see
        # select_care_contexts()'s multi_select mode and
        # generate_link_token()'s selected_care_context_references
        # param). None means "link everything found," matching the
        # prior, only behavior.
        selected_refs = pending.get("selected_care_context_references")
        if selected_refs:
            patient_data = [
                record for record in patient_data
                if record["care_context_reference"] in selected_refs
            ]

        if not patient_data:
            # Guards against the same empty-"patient"-array 400 fixed
            # earlier today (ABDM-9999 "patient attribute required in
            # the payload") -- this time caused by a selection that
            # matched nothing (e.g. stale references) rather than a
            # data mismatch.
            log_error(
                f"No care context records to link for {resolved_abha_address} "
                f"after applying the caller's selection (selected_care_context_references="
                f"{selected_refs!r}) -- skipping link_care_context() call."
            )
            delete_pending_link_token(request_id)
            return

        patient_records = build_patient_payload(patient_data)

        response = link_care_context(
            hip_id=pending["hip_id"],
            abha_address=resolved_abha_address,
            link_token=link_token,
            patient_records=patient_records,
            abha_number=pending.get("abha_number"),
        )

        log_api_call("Linking care context with ABDM", "POST .../link/carecontext", response.status_code)

        delete_pending_link_token(request_id)

        if response.status_code != 202:
            print_api_response(response)
            return

        log_waiting("Waiting for ABDM's on_carecontext confirmation")

    except Exception as exc:
        log_error(f"Generate Token callback processing failed unexpectedly: {exc}")
        return
