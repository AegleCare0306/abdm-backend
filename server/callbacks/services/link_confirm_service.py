import asyncio
from datetime import datetime, timezone

from server.callbacks.repository.link_repository import get_link_session
from server.callbacks.repository.patient_repository import search_patient
from server.callbacks.transformers.patient_transformer import build_patient_payload
from server.callbacks.services.otp_service import verify_otp
from server.linking import send_on_confirm
from server.utils import print_api_response
from server.callbacks.repository.patient_identity_repository import get_patient_identity
from server.callbacks.utils.idempotency import already_processed, mark_processed
from server.callbacks.utils.flow_logger import log_phase, log_api_call, log_error

# See server/callbacks/utils/idempotency.py's own docstring, and
# consent_notify_service.py's use of the same pattern (tracker case
# M2-9) -- this closes the sibling case M2-11 ("sending the same 'link
# confirmed' message twice creates duplicate linked records"). On a
# detected replay this skips re-verifying the OTP and re-triggering
# send_on_confirm() entirely rather than attempting to resend an
# identical ack -- the first, genuine processing already sent ABDM its
# on-confirm; running verify_otp()/search_patient()/send_on_confirm()
# a second time for the same message is exactly the duplicate-work this
# guard exists to prevent.
#
# RETRY-EXHAUSTION FIX (tracker case M2-54): that reasoning only covers
# a replay of a message we already fully, successfully processed. It
# didn't cover the case where the FIRST attempt got all the way through
# verify_otp()/search_patient()/build_patient_payload() but then
# send_on_confirm() itself permanently failed (call_with_retry exhausted
# its retries and raised) -- mark_processed() had already run by then,
# so the old code's replay branch just logged "already processed" and
# returned, meaning ABDM would NEVER receive an on-confirm ack for this
# link, even though the CM/gateway keeps redelivering the identical
# confirm request (same REQUEST-ID, same confirmation.linkRefNumber --
# unlike link_init's own version of this bug, M2-55, this message is
# forwarded by ABDM/the CM, not something WE generated, so a redelivery
# genuinely carries the same linkRefNumber back to us). The replay
# branch now checks whether the stored link session is still around
# (proof the real work -- OTP verification, record lookup -- already
# completed) and, if so, safely RE-SENDS just the ack: it never calls
# verify_otp() again (a single-use OTP token must not be re-consumed),
# only the read-only/side-effect-free steps (session lookup, patient
# identity lookup, record search, payload build) plus the outbound ack
# call itself.
_IDEMPOTENCY_SCOPE = "link_confirm"


async def process_link_confirm(callback_data):

    try:
        log_phase("Patient submitted OTP -- confirming link (POST /api/v3/hip/link/care-context/confirm)")

        headers = callback_data["headers"]
        body = callback_data["body"]
        confirmation = body.get("confirmation", {})

        # SHAPE GUARD (tracker case M2-27, bonus hardening): the {}
        # default above only covers a MISSING "confirmation" key -- if
        # it's present but shaped unexpectedly (a string, a list, ...),
        # confirmation.get(...) below would raise AttributeError. The
        # rest of this function already handles individually-missing
        # fields cleanly (both are read via .get(), and link_reference_number
        # being None already flows into a clean "Link session not found"
        # log_error below) -- this just extends that same clean-error
        # behavior to a malformed "confirmation" object too.
        if not isinstance(confirmation, dict):
            log_error(f"Link confirm request's 'confirmation' field was not an object (got {type(confirmation).__name__}) -- cannot confirm.")
            return

        request_id = headers.get("request-id")
        otp = confirmation.get("token")
        link_reference_number = confirmation.get("linkRefNumber")

        if already_processed(_IDEMPOTENCY_SCOPE, request_id):
            log_phase(f"REQUEST-ID {request_id} already processed for link_confirm -- treating as a replay, skipping re-verification and re-confirmation, but re-sending the ack in case the first ack attempt never actually reached ABDM.")
            await _resend_confirm_ack(link_reference_number, request_id)
            return

        mark_processed(_IDEMPOTENCY_SCOPE, request_id)

        session = get_link_session(link_reference_number)

        if session is None:
            log_error("Link session not found -- cannot confirm.")
            return

        # CORRUPTED-SESSION GUARD (tracker case M2-28): the OLD code read
        # session["otp_txn_id"]/session["abha_address"]/
        # session["selected_patient_records"] via direct key access
        # further down. A corrupted stored session missing one of these
        # fields raised a KeyError that WAS caught by this function's
        # outer try/except (so not a silent crash), but the resulting
        # message was just Python's own KeyError repr (e.g. just
        # "'otp_txn_id'") -- accurate, but not as clear as this
        # codebase's usual explicit log_error() messages. Checking each
        # required field up front gives a specific, readable reason
        # instead of relying on an accidental exception message.
        required_fields = ["otp_txn_id", "abha_address", "selected_patient_records"]
        missing_fields = [f for f in required_fields if session.get(f) is None]
        if missing_fields:
            log_error(f"Link session for {link_reference_number} is missing required field(s) {missing_fields} -- cannot confirm (corrupted or incomplete session).")
            return

        expiry_str = session.get("otp_expiry")
        if expiry_str:
            expiry_dt = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expiry_dt:
                log_error("OTP window has expired -- cannot confirm link.")
                return

        # Off the event loop thread -- see discover_service.py's
        # process_discover() for why every blocking requests.* call
        # reachable from an async def callback handler is wrapped this way.
        # verify_otp() (otp_service.py) itself stays synchronous; it
        # internally calls get_public_certificate() and abha.py's own
        # verify_otp() -- both move to the worker thread together as one
        # unit along with this call.
        if not await asyncio.to_thread(
                verify_otp,
                otp=otp,
                txn_id=session["otp_txn_id"],
        ):
            log_error("OTP verification failed.")
            return

        patient = get_patient_identity(
            session["abha_address"]
        )

        if patient is None:
            log_error("Patient identity not found -- cannot confirm link.")
            return

        if patient.get("hip_id") is None:
            log_error(f"Patient identity for {session['abha_address']} is missing 'hip_id' -- cannot confirm (corrupted or incomplete record).")
            return

        records = search_patient(
        abha_address=session["abha_address"],
        hip_id=patient["hip_id"],
        patient_selection=session["selected_patient_records"])

        patient_payload = build_patient_payload(records)

        response = await asyncio.to_thread(
            send_on_confirm,
            patient=patient_payload,
            request_id=request_id,
        )

        log_api_call("Confirming Successful Link with ABDM", "POST .../on-confirm", response.status_code)

        if response.status_code != 202:
            print_api_response(response)
            return

        log_phase("Patient's records are now linked")

    except Exception as exc:
        log_error(f"Link Confirm callback processing failed unexpectedly: {exc}")
        return


async def _resend_confirm_ack(link_reference_number, request_id):
    """
    Re-sends the on-confirm ack for a replayed link_confirm message
    (tracker case M2-54), WITHOUT re-verifying the OTP or assuming
    anything succeeded the first time. Re-derives the patient payload
    from scratch (session lookup, patient identity lookup, record
    search, payload build are all read-only/side-effect-free, so
    re-running them is safe) and re-sends send_on_confirm() -- if the
    first attempt's ack genuinely never reached ABDM (call_with_retry
    exhausted), this is the only way it ever will.

    Never raises -- called from inside process_link_confirm()'s own
    already_processed() branch, itself inside that function's outer
    try/except, so any failure here is still caught and logged there.
    """

    session = get_link_session(link_reference_number)

    if session is None:
        log_error(f"Cannot re-send on-confirm ack for a replayed link_confirm (requestId {request_id!r}) -- no link session found for linkRefNumber {link_reference_number!r} (already cleaned up, or this replay's linkRefNumber doesn't match the original).")
        return

    required_fields = ["abha_address", "selected_patient_records"]
    missing_fields = [f for f in required_fields if session.get(f) is None]
    if missing_fields:
        log_error(f"Cannot re-send on-confirm ack -- link session for {link_reference_number} is missing required field(s) {missing_fields}.")
        return

    patient = get_patient_identity(session["abha_address"])

    if patient is None or patient.get("hip_id") is None:
        log_error(f"Cannot re-send on-confirm ack -- patient identity for {session['abha_address']} not found or missing 'hip_id'.")
        return

    records = search_patient(
        abha_address=session["abha_address"],
        hip_id=patient["hip_id"],
        patient_selection=session["selected_patient_records"],
    )

    patient_payload = build_patient_payload(records)

    response = await asyncio.to_thread(
        send_on_confirm,
        patient=patient_payload,
        request_id=request_id,
    )

    log_api_call("Confirming Successful Link with ABDM (replay -- re-sent ack)", "POST .../on-confirm", response.status_code)

    if response.status_code != 202:
        print_api_response(response)
