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
_IDEMPOTENCY_SCOPE = "link_confirm"


async def process_link_confirm(callback_data):

    try:
        log_phase("Patient submitted OTP -- confirming link (POST /api/v3/hip/link/care-context/confirm)")

        headers = callback_data["headers"]
        body = callback_data["body"]
        confirmation = body.get("confirmation", {})

        request_id = headers.get("request-id")
        otp = confirmation.get("token")
        link_reference_number = confirmation.get("linkRefNumber")

        if already_processed(_IDEMPOTENCY_SCOPE, request_id):
            log_phase(f"REQUEST-ID {request_id} already processed for link_confirm -- treating as a replay, skipping re-verification and re-confirmation.")
            return

        mark_processed(_IDEMPOTENCY_SCOPE, request_id)

        session = get_link_session(link_reference_number)

        if session is None:
            log_error("Link session not found -- cannot confirm.")
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
