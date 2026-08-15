import asyncio
import json

from server.linking import send_on_init
from server.utils import generate_request_id, generate_expiry_time, print_api_response
from server.callbacks.repository.link_repository import save_link_session, get_all_link_sessions
from server.callbacks.repository.patient_identity_repository import get_patient_identity
from server.crypto import encrypt_value, get_public_certificate
from server.abha import request_otp
from server.callbacks.utils.idempotency import already_processed, mark_processed
from server.callbacks.utils.flow_logger import log_phase, log_api_call, log_waiting, log_error

# See server/callbacks/utils/idempotency.py's own docstring, and
# consent_notify_service.py's use of the same pattern (tracker case
# M2-9) -- this closes the sibling case M2-13 ("a duplicated linking
# request requests a second, brand-new OTP from ABDM and saves a
# second link session under a second reference number"). On a detected
# replay this skips requesting a fresh OTP and saving a second session
# entirely.
#
# RETRY-EXHAUSTION FIX (tracker case M2-55): that reasoning only covers
# a replay of a message we already fully, successfully processed. It
# didn't cover the case where the FIRST attempt got all the way through
# requesting the OTP and saving the session, but send_on_init() itself
# then permanently failed (call_with_retry exhausted its retries and
# raised) -- mark_processed() had already run by then, so the old code's
# replay branch just logged "already processed" and returned, meaning
# ABDM would NEVER receive an on-init ack (and never learn our
# link_reference_number) for this transaction, even if ABDM keeps
# redelivering the identical link/init request. Unlike link_confirm's
# version of this bug (M2-54), the redelivered request body here doesn't
# carry OUR link_reference_number back to us (we invented it; ABDM only
# learns it FROM our on-init ack, which is exactly the message that got
# lost) -- so recovering it means looking it up by the one thing the
# replay DOES carry: the same REQUEST-ID. See
# _find_link_session_by_request_id() below.
_IDEMPOTENCY_SCOPE = "link_init"


async def process_link_init(callback_data):

    try:
        log_phase("Patient chose to link records -- link request received (POST /api/v3/hip/link/care-context/init)")

        body = callback_data["body"]
        headers = callback_data["headers"]

        abha_address = body.get("abhaAddress")
        transaction_id = body.get("transactionId")
        request_id = headers.get("request-id")
        patient_records= body.get("patient", [])

        if already_processed(_IDEMPOTENCY_SCOPE, request_id):
            log_phase(f"REQUEST-ID {request_id} already processed for link_init -- treating as a replay, skipping a second OTP request/link session, but re-sending the on-init ack in case the first ack attempt never actually reached ABDM.")
            await _resend_init_ack(request_id)
            return

        mark_processed(_IDEMPOTENCY_SCOPE, request_id)

        link_reference_number = generate_request_id()

        patient = get_patient_identity(
            abha_address,
        )

        if patient is None:
            log_error("Patient identity not found -- cannot proceed with link.")
            return

        log_phase("Extracted care contexts the patient wants to link")

        encrypted_abha_number = encrypt_value(
            patient["abha_number"],get_public_certificate()
        )

        # Off the event loop thread -- see discover_service.py's
        # process_discover() for why every blocking requests.* call
        # reachable from an async def callback handler is wrapped this way.
        otp_response = await asyncio.to_thread(
            request_otp,
            action="profile/login",
            scope=["abha-login", "mobile-verify"],
            login_hint="abha-number",
            login_id=encrypted_abha_number,
            otp_system="abdm"

        )

        log_api_call("Requesting OTP for Patient Verification", "POST .../profile/login/request/otp", otp_response.status_code)

        if otp_response.status_code != 200:
            print_api_response(otp_response)
            return

        otp_txn_id = otp_response.json()["txnId"]

        otp_expiry = generate_expiry_time()

        session_data = {
            "transaction_id": transaction_id,
            "request_id": request_id,
            "abha_address": abha_address,
            "selected_patient_records": patient_records,
            "otp_txn_id": otp_txn_id,
            "otp_expiry": otp_expiry,
        }

        save_link_session(
            link_reference_number,
            session_data
        )

        response = await asyncio.to_thread(
            send_on_init,
            transaction_id=transaction_id,
            request_id=request_id,
            link_reference_number=link_reference_number,
            authentication_type="DIRECT",
            communication_medium="MOBILE",
            communication_hint="OTP",
            communication_expiry=otp_expiry,
        )

        log_api_call("Confirming Link Initiated with ABDM", "POST .../on-init", response.status_code)

        if response.status_code != 202:
            print_api_response(response)
            return

        log_waiting("Waiting for the patient to enter the OTP sent to their mobile/email")

    except Exception as exc:
        log_error(f"Link Init callback processing failed unexpectedly: {exc}")
        return


def _find_link_session_by_request_id(request_id):
    """
    Reverse-looks-up a stored link session by the REQUEST-ID that
    created it, since link sessions are keyed by link_reference_number
    (a value WE generate, not something the inbound link/init request
    carries), not by request_id.

    Repurposes get_all_link_sessions() (link_repository.py -- its own
    docstring marks it "Debugging Only; no caller in this codebase
    today"), scanning every stored session for the one whose own
    "request_id" field matches. Correct but O(n) in the number of link
    sessions ever created and never cleaned up -- acceptable here since
    this only runs on the rare path of a replayed link/init request,
    not on every request.

    Returns:
        (link_reference_number, session_data) | (None, None)
    """
    for link_reference_number, session_data in get_all_link_sessions().items():
        if session_data.get("request_id") == request_id:
            return link_reference_number, session_data
    return None, None


async def _resend_init_ack(request_id):
    """
    Re-sends the on-init ack for a replayed link_init message (tracker
    case M2-55), WITHOUT requesting a second OTP or saving a second
    session. Looks up the session already saved by the first attempt
    (see _find_link_session_by_request_id() above) and re-sends
    send_on_init() with the SAME link_reference_number/otp_expiry it
    already generated -- if the first attempt's ack genuinely never
    reached ABDM (call_with_retry exhausted), this is the only way it
    ever will, and ABDM only ever learns our link_reference_number
    through this ack.

    Never raises -- called from inside process_link_init()'s own
    already_processed() branch, itself inside that function's outer
    try/except, so any failure here is still caught and logged there.
    """

    link_reference_number, session = _find_link_session_by_request_id(request_id)

    if session is None:
        log_error(f"Cannot re-send on-init ack for a replayed link_init (requestId {request_id!r}) -- no stored link session was found with this request_id (already cleaned up, or the first attempt failed before the session was ever saved -- in which case there's nothing to resend and the patient will need to retry link init from scratch).")
        return

    required_fields = ["transaction_id", "otp_expiry"]
    missing_fields = [f for f in required_fields if session.get(f) is None]
    if missing_fields:
        log_error(f"Cannot re-send on-init ack -- link session for {link_reference_number} is missing required field(s) {missing_fields}.")
        return

    response = await asyncio.to_thread(
        send_on_init,
        transaction_id=session["transaction_id"],
        request_id=request_id,
        link_reference_number=link_reference_number,
        authentication_type="DIRECT",
        communication_medium="MOBILE",
        communication_hint="OTP",
        communication_expiry=session["otp_expiry"],
    )

    log_api_call("Confirming Link Initiated with ABDM (replay -- re-sent ack)", "POST .../on-init", response.status_code)

    if response.status_code != 202:
        print_api_response(response)
