from server.callbacks.repository.care_context_link_repository import get_pending_care_context_link, delete_pending_care_context_link
from server.hip_linking import notify_care_context_update
from server.callbacks.utils.flow_logger import log_phase, log_api_call, log_error


async def process_care_context_link(callback_data):

    try:
        log_phase("ABDM confirmed the care context link result (POST /api/v3/link/on_carecontext)")

        body = callback_data["body"]

        abha_address = body.get("abhaAddress")
        status = body.get("status")
        error = body.get("error")
        request_id = body.get("response", {}).get("requestId")

        pending = get_pending_care_context_link(request_id) if request_id else None

        if error:
            log_error(f"Care context linking failed for {abha_address}: {error}")

            if pending is not None:
                delete_pending_care_context_link(request_id)

            return

        log_phase(f"Care context successfully linked for {abha_address}: {status}")

        # Step 3 of the chain (M2 doc §4.3.6): auto-trigger Notify Care
        # Context Update for every care context that was just linked,
        # since on_carecontext's own body doesn't say which ones those
        # were -- that's what link_care_context() stashed here before
        # its outbound call (see hip_linking.py's _invert_for_notify()).
        if pending is None:
            log_error(
                f"No pending care context link session found for requestId {request_id!r} "
                f"-- skipping auto-triggered Notify Care Context Update."
            )
            return

        resolved_abha_address = abha_address or pending["abha_address"]

        for care_context_reference, hi_types in pending["care_context_hi_types"].items():

            try:
                notify_response = notify_care_context_update(
                    hip_id=pending["hip_id"],
                    abha_address=resolved_abha_address,
                    patient_reference=pending["patient_reference"],
                    care_context_reference=care_context_reference,
                    hi_types=hi_types,
                    link_token=pending["link_token"],
                )

                log_api_call(
                    f"Notifying care context update for {care_context_reference}",
                    "POST .../link/context/notify",
                    notify_response.status_code,
                )

                if notify_response.status_code != 202:
                    log_error(
                        f"Notify Care Context Update for {care_context_reference} returned "
                        f"unexpected status {notify_response.status_code} -- continuing with "
                        f"the remaining care contexts."
                    )

            except Exception as exc:
                # One failed Notify call (network error or otherwise) must
                # not stop the rest -- each care context is independent.
                log_error(f"Notify Care Context Update for {care_context_reference} failed unexpectedly: {exc}")

        delete_pending_care_context_link(request_id)

    except Exception as exc:
        log_error(f"Care Context Link callback processing failed unexpectedly: {exc}")
        return
