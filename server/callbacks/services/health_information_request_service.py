import asyncio
import hashlib
import json

from server.callbacks.repository.health_information_repository import (
    save_health_information_session,
    update_health_information_session,
)
from server.callbacks.repository.consent_repository import get_consent
from server.callbacks.services.health_information_data_service import build_bundles_for_care_contexts
from server.healthinformation import (
    send_on_health_information_request,
    send_health_information_data,
    send_health_information_notify,
)
from server.fidelius_crypto import generate_key_material, encrypt_health_data, to_x509_public_key
from server.utils import print_api_response, generate_timestamp, generate_expiry_time, generate_safe_past_timestamp
from server.callbacks.utils.idempotency import already_processed, mark_processed
from server.callbacks.utils.flow_logger import log_phase, log_api_call, log_waiting, log_error
from server.callbacks.utils.attachment_metrics import time_block, mechanisms_in_bundle

# See server/callbacks/utils/idempotency.py's own docstring, and
# consent_notify_service.py's use of the same pattern (tracker case
# M2-9) -- this closes the sibling case M2-10 ("replaying an old
# health-data request causes the same patient data to be sent out
# twice, under two different encryption keys"). _push_and_notify()
# generates a fresh ECDH key pair per care context on every call (by
# design, for forward secrecy -- see that function's own docstring), so
# a raw replay of this callback with no guard would re-encrypt and
# re-push every record under brand-new keys, and re-notify ABDM a
# second time for a transfer that already completed.
_IDEMPOTENCY_SCOPE = "health_information_request"


def _compute_checksum(encrypted_content):
    """
    MD5 hex digest of the encrypted content. Confirmed (not guessed) via an
    independent source documenting real ABDM HIP integrations -- an earlier
    version of this used SHA-256 as an unconfirmed placeholder; that was
    wrong. This resolves the same "what should checksum be" question that
    came up earlier around the "string" ambiguity from the demo video.
    """
    return hashlib.md5(encrypted_content.encode("utf-8")).hexdigest()


def _push_and_notify(
    fhir_bundles,
    data_push_url,
    hiu_key_material,
    transaction_id,
    consent_id,
    hip_id,
):
    """
    fhir_bundles: {care_context_reference: bundle}, as returned by
    build_bundles_for_care_contexts(). Keyed rather than positional
    deliberately -- that function can return fewer bundles than were
    requested (encounter missing, or filtered out by the consent's
    dateRange), and zipping bundles against the full requested list would
    mis-attribute every bundle after the first gap, pushing one care
    context's data to ABDM labelled as another's.

    ONE PUSH CALL PER CARE CONTEXT, EACH WITH ITS OWN FRESH KEY MATERIAL
    (changed 2026-08-12 -- see the Notion flag this closes for the full
    writeup): this used to generate ONE hip_key_material for the whole
    transaction and reuse it (same derived AES key AND the same AES-GCM
    IV, since both are deterministic functions of the two nonces --
    see fidelius_crypto.py's _derive_key_and_iv()) across every entry in
    a single push call. That's a real AES-GCM nonce-reuse condition for
    any consent covering more than one care context.

    This can't be fixed by just generating a fresh key without changing
    the wire shape: ABDM's data-push payload carries exactly ONE
    `keyMaterial` field alongside the `entries` array, so a receiving HIU
    has no way to know a different key was used per entry within one
    push call -- there is nowhere in the schema to carry more than one
    keyMaterial per call. The payload's existing pageNumber/pageCount
    fields are exactly the mechanism ABDM already defines for exactly
    this situation: instead of one push carrying N entries under one
    shared keyMaterial, this now makes N separate push calls -- one per
    care context, each its own page, each with its own freshly generated
    ephemeral ECDH key pair and nonce (hence its own independent derived
    AES key and IV). No entry ever shares key material with another
    again.

    IMPACT ON THE RECEIVING SIDE: this is a wire-format change (multiple
    pushes per transaction is now the normal case, not just a
    theoretical possibility the schema always allowed). See
    server/callbacks/services/health_information_hiu_push_service.py --
    it previously treated every push as a complete, standalone
    transaction (single notify per push, storage overwritten per push,
    which would have silently discarded every page but the last). It was
    updated in the same change to merge care_contexts across pages for a
    transactionId and only send the final notify once the last page
    (pageNumber == pageCount - 1) has arrived. See that file's own
    docstring/comments for the details. tools/m3_test_suite's CLI poll
    was updated to match (waits for the last page specifically, not just
    the first push callback it sees).

    A single-care-context transfer (the common case in testing so far)
    is page_count=1, page_number=0 -- behaviourally identical to before
    except for the fresh-key generation itself.
    """

    care_context_refs = list(fhir_bundles.keys())
    total_entries = len(care_context_refs)

    status_responses = []
    records_by_care_context = {}
    encrypted_bundle_by_care_context = {}
    checksum_by_care_context = {}
    all_mechanisms = set()
    pushed_count = 0

    for page_number, care_context_reference in enumerate(care_context_refs):

        bundle = fhir_bundles[care_context_reference]
        bundle_mechanisms = mechanisms_in_bundle(bundle)
        all_mechanisms.update(bundle_mechanisms)

        plaintext = json.dumps(bundle)

        # Fresh per entry/page -- this is the fix itself. See this
        # function's own docstring above.
        hip_key_material = generate_key_material()

        try:
            with time_block(
                "encrypt",
                transaction_id=transaction_id,
                care_context_reference=care_context_reference,
                mechanisms=bundle_mechanisms,
            ):
                encrypted_content = encrypt_health_data(
                    plaintext=plaintext,
                    sender_private_key=hip_key_material["private_key"],
                    sender_nonce=hip_key_material["nonce"],
                    requester_public_key=hiu_key_material["dhPublicKey"]["keyValue"],
                    requester_nonce=hiu_key_material["nonce"],
                )
        except Exception as exc:
            log_error(f"Encryption failed for care context {care_context_reference}: {exc}")
            status_responses.append({
                "careContextReference": care_context_reference,
                "hiStatus": "ERRORED",
                "description": f"Encryption failed: {exc}",
            })
            continue

        entry = {
            "content": encrypted_content,
            "media": "application/fhir+json",
            "checksum": _compute_checksum(encrypted_content),
            "careContextReference": care_context_reference,
        }

        records_by_care_context[care_context_reference] = bundle
        encrypted_bundle_by_care_context[care_context_reference] = entry["content"]
        checksum_by_care_context[care_context_reference] = entry["checksum"]

        # Our own public key must be sent in X.509 DER format -- confirmed
        # as the actual root cause of the earlier "ABDM-9999: Could not
        # read encrypted content" 400 error. The INCOMING HIU key stays
        # raw uncompressed (that direction is confirmed correct already);
        # only our OUTBOUND key needed this conversion.
        outbound_key_material = {
            "cryptoAlg": "ECDH",
            "curve": "Curve25519",
            "dhPublicKey": {
                "expiry": generate_expiry_time(minutes=60),
                "parameters": "Curve25519/32byte random key",
                "keyValue": to_x509_public_key(hip_key_material["public_key"]),
            },
            "nonce": hip_key_material["nonce"],
        }

        # Each page's HTTP call is isolated in its own try/except -- same
        # pattern as the encryption step above. Confirmed live (2026-08-12)
        # that WITHOUT this, a network-level exception (connection drop,
        # timeout, DNS failure -- anything requests raises rather than
        # returning a bad status for) on any one page propagates straight
        # out of this whole function: remaining pages are never attempted,
        # AND the final notify below never runs, even though earlier pages
        # in this same loop may have already been genuinely delivered.
        # Before per-page pushing existed there was only one push call for
        # the whole transaction, so "exception -> no notify" meant "nothing
        # was delivered" -- atomic and self-consistent. With per-page
        # pushing that's no longer true: an exception on page 3 of 5 could
        # leave pages 1-2 truly received by the HIU with zero record
        # anywhere that it happened. This except turns that into one more
        # ERRORED entry and lets the loop continue, so the final notify
        # always fires with an honest picture of what did and didn't make
        # it -- instead of silently dropping everything after the failure
        # point. A graceful non-200 response (no exception) was already
        # handled correctly before this change and is unaffected here.
        try:
            with time_block(
                "transmit",
                transaction_id=transaction_id,
                care_context_reference=care_context_reference,
                mechanisms=sorted(bundle_mechanisms),
            ):
                push_response = send_health_information_data(
                    data_push_url=data_push_url,
                    transaction_id=transaction_id,
                    entries=[entry],
                    key_material=outbound_key_material,
                    page_number=page_number,
                    page_count=total_entries,
                    attachment_mechanisms=sorted(bundle_mechanisms),
                )
        except Exception as exc:
            log_error(f"Push failed for care context {care_context_reference}: {exc}")
            status_responses.append({
                "careContextReference": care_context_reference,
                "hiStatus": "ERRORED",
                "description": f"Push failed: {exc}",
            })
            continue

        log_api_call(
            f"Pushing Encrypted Record ({care_context_reference}, page {page_number + 1}/{total_entries}) to HIU",
            f"POST {data_push_url}",
            push_response.status_code,
        )

        pushed_ok = push_response.status_code == 200
        if pushed_ok:
            pushed_count += 1

        status_responses.append({
            "careContextReference": care_context_reference,
            "hiStatus": "DELIVERED" if pushed_ok else "ERRORED",
            "description": "Transferred successfully" if pushed_ok else f"Push failed with status {push_response.status_code}",
        })

        if not pushed_ok:
            print_api_response(push_response)

    session_status = "TRANSFERRED" if pushed_count > 0 else "FAILED"

    # records_by_care_context / encrypted_bundle_by_care_context /
    # checksum_by_care_context were populated inside the loop above (only
    # for entries that actually made it through encryption) -- no need to
    # rebuild them here. Previously this rebuilt them post-loop from a
    # single shared `entries` list; that list no longer exists now that
    # each entry is pushed individually (see this function's docstring).

    update_health_information_session(
        transaction_id,
        {
            "records": records_by_care_context,
            "encrypted_bundle": encrypted_bundle_by_care_context,
            "checksum": checksum_by_care_context,
            "transfer_status": session_status,
        },
    )

    notify_response = send_health_information_notify(
        consent_id=consent_id,
        transaction_id=transaction_id,
        hip_id=hip_id,
        done_at=generate_safe_past_timestamp(),
        session_status=session_status,
        status_responses=status_responses,
    )

    log_api_call("Notifying ABDM of Transfer Outcome", "POST .../health-information/notify", notify_response.status_code)

    if notify_response.status_code != 202:
        print_api_response(notify_response)

    if session_status == "TRANSFERRED":
        log_phase("Records delivered to the HIU successfully")
    else:
        log_error("Records were not successfully delivered to the HIU -- see status responses above")


async def process_health_information_request(
    callback_data,
):

    try:
        log_phase("Data request received -- HIU wants the patient's records (POST /api/v3/hip/health-information/request)")

        headers = callback_data["headers"]
        body = callback_data["body"]

        request_id = headers.get("request-id")
        hip_id = headers.get("x-hip-id")
        transaction_id = body.get("transactionId")

        if already_processed(_IDEMPOTENCY_SCOPE, request_id):
            log_phase(f"REQUEST-ID {request_id} already processed for health_information_request -- treating as a replay, re-acking but skipping a second encrypt+push+notify cycle.")
            response = await asyncio.to_thread(
                send_on_health_information_request,
                transaction_id=transaction_id,
                request_id=request_id,
            )
            log_api_call("Acknowledging Data Request to ABDM (replay)", "POST .../hip/on-request", response.status_code)
            if response.status_code != 200:
                print_api_response(response)
            return

        mark_processed(_IDEMPOTENCY_SCOPE, request_id)

        hi_request = body.get("hiRequest",{})
        consent_id = (hi_request.get("consent", {}).get("id"))
        date_range = hi_request.get("dateRange",{})
        data_push_url = hi_request.get("dataPushUrl")
        key_material = hi_request.get("keyMaterial",{})

        log_phase("Extracted consent ID, approved care contexts, and encryption keys")

        consent = get_consent(consent_id)

        care_context_references = []
        fhir_bundles = None

        if consent is None:
            log_error(f"No stored consent artifact found for consentId={consent_id} -- cannot build records (was it ever GRANTED?).")
        else:
            # MALFORMED-SHAPE GUARD (edge-case-review pass, tracker case
            # M2-16): the OLD code assumed consent.get("care_contexts", [])
            # is always a list of dicts. A corrupted/hand-edited stored
            # consent record (or a future write-side bug) with
            # care_contexts stored as None, a string, a dict, or a list
            # containing non-dict entries would raise an unhandled
            # AttributeError/TypeError here -- caught by this function's
            # outer try/except, but only AFTER mark_processed() already
            # ran and BEFORE send_on_health_information_request() ever
            # fires, so ABDM never gets an ack at all and just sees a
            # silent timeout, with nothing but a log line as evidence.
            # Normalizing defensively here (same "log clearly, treat as
            # empty rather than crash" shape as the M1-10/M1-12 guards in
            # login_runner.py) lets processing continue far enough to
            # still send ABDM a proper ack -- with zero care contexts if
            # the stored record is unusable, rather than none at all.
            stored_care_contexts = consent.get("care_contexts")
            if not isinstance(stored_care_contexts, list):
                if stored_care_contexts is not None:
                    log_error(
                        f"Stored consent {consent_id} has a malformed 'care_contexts' field "
                        f"(expected a list, got {type(stored_care_contexts).__name__}: "
                        f"{stored_care_contexts!r}) -- treating as no approved care contexts "
                        f"rather than crashing."
                    )
                stored_care_contexts = []

            care_context_references = [
                care_context.get("careContextReference")
                for care_context in stored_care_contexts
                if isinstance(care_context, dict) and care_context.get("careContextReference")
            ]

            # Off the event loop thread (tracker case M2-6): building the
            # FHIR bundles for every approved care context is real
            # CPU-bound work (reading/serializing potentially many large
            # records/attachments), previously run directly inline in
            # this async handler -- blocking the single uvicorn worker's
            # event loop, and every other in-flight request on this
            # server, for however long assembly takes. Same fix pattern
            # as M2-5 (health_information_hiu_push_service.py's
            # _decrypt_entries()) -- the whole timed block moves to a
            # worker thread as one unit so time_block()'s own timing
            # still wraps the real work being measured.
            def _assemble_bundles():
                with time_block("bundle_assembly", transaction_id=transaction_id):
                    return build_bundles_for_care_contexts(care_context_references, date_range=date_range)

            fhir_bundles = await asyncio.to_thread(_assemble_bundles)
            log_phase(f"Assembled {len(fhir_bundles)} FHIR record(s) for the approved care context(s)")

        session_data = {
            "request_id": request_id,
            "transaction_id": transaction_id,
            "hip_id": hip_id,
            "consent_id": consent_id,
            "care_context_references": care_context_references,
            "date_range": date_range,
            "data_push_url": data_push_url,
            "key_material": key_material,

            "body": body,

            "records": None,
            "fhir_bundles": fhir_bundles,
            "encrypted_bundle": None,
            "checksum": None,
            "transfer_status": None,
        }

        save_health_information_session(
            transaction_id,
            session_data,
        )

        # Off the event loop thread -- see discover_service.py's
        # process_discover() for why every blocking requests.* call
        # reachable from an async def callback handler is wrapped this way.
        response = await asyncio.to_thread(
            send_on_health_information_request,
            transaction_id=transaction_id,
            request_id=request_id,
        )

        log_api_call("Acknowledging Data Request to ABDM", "POST .../hip/on-request", response.status_code)

        if response.status_code != 200:
            print_api_response(response)
            return

        if not fhir_bundles or not data_push_url or not key_material:

            if not fhir_bundles:
                # No parentheses in this string -- ABDM's health-information/notify
                # endpoint rejected this exact description with "ABDM-9999:
                # Invalid description" (a genuine 400 seen live, 2026-08-11)
                # when it read "...care context(s)."; an otherwise
                # identically-shaped FAILED/ERRORED notify call using a
                # description with no parentheses ("Push failed with status
                # 503") was accepted (202) the day before. Not a confirmed,
                # documented ABDM rule -- just the one direct comparison
                # available -- so treat this as a working hypothesis until
                # confirmed by a clean live retest.
                reason = "Could not prepare any FHIR records for the approved care contexts."
            elif not data_push_url:
                reason = "HIU did not provide a dataPushUrl in the request -- unable to deliver records."
            elif not key_material:
                reason = "HIU did not provide keyMaterial in the request -- unable to encrypt records for delivery."

            # Assumption: an empty status_responses list (e.g. when no consent was
            # found at all, so care_context_references is empty) is accepted by
            # ABDM's schema -- not a confirmed detail.
            status_responses = [
                {"careContextReference": ref, "hiStatus": "ERRORED", "description": reason}
                for ref in care_context_references
            ]

            notify_response = await asyncio.to_thread(
                send_health_information_notify,
                consent_id=consent_id,
                transaction_id=transaction_id,
                hip_id=hip_id,
                done_at=generate_safe_past_timestamp(),
                session_status="FAILED",
                status_responses=status_responses,
            )

            log_api_call("Notifying ABDM of Transfer Outcome", "POST .../health-information/notify", notify_response.status_code)

            if notify_response.status_code != 202:
                print_api_response(notify_response)

            log_error(reason)
            return

        log_waiting("Encrypting and pushing records to the HIU")

        # THE DEADLOCK FIX: _push_and_notify() is a plain synchronous
        # function that internally calls send_health_information_data()
        # (a blocking requests.post()) and then send_health_information_notify()
        # sequentially, as one logical unit (encrypt -> push -> notify).
        # Confirmed live: because this server runs both the M2 HIP role and
        # the M3 HIU role in one process, data_push_url here can be our OWN
        # server's dataPushUrl -- so without this wrap, this HIP-role code
        # (already running inside this same event loop, handling this
        # inbound health_information_request callback) would block that
        # loop making a synchronous call back into itself, waiting on a
        # response only that same (now-blocked) loop could ever serve.
        # Genuine deadlock, reproduced and fixed 2026-08-10. Wrapping the
        # whole _push_and_notify() call (rather than making it async def,
        # or wrapping its two internal calls separately) moves the entire
        # synchronous chain to a worker thread as one piece, leaving this
        # function's own internal logic/control-flow untouched.
        await asyncio.to_thread(
            _push_and_notify,
            fhir_bundles=fhir_bundles,
            data_push_url=data_push_url,
            hiu_key_material=key_material,
            transaction_id=transaction_id,
            consent_id=consent_id,
            hip_id=hip_id,
        )

    except Exception as exc:
        log_error(f"Health Information Request callback processing failed unexpectedly: {exc}")
        return
