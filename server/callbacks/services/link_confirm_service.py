from server.callbacks.repository.link_repository import get_link_session
from server.callbacks.repository.patient_repository import search_patient
from server.callbacks.transformers.patient_transformer import build_patient_payload
from server.callbacks.services.otp_service import verify_otp
from server.linking import send_on_confirm
from server.utils import print_api_response
from server.callbacks.repository.patient_identity_repository import get_patient_identity
from server.callbacks.utils.flow_logger import log_phase, log_api_call, log_error


async def process_link_confirm(callback_data):

    try:
        log_phase("Patient submitted OTP -- confirming link (POST /api/v3/hip/link/care-context/confirm)")

        headers = callback_data["headers"]
        body = callback_data["body"]
        confirmation = body.get("confirmation", {})

        request_id = headers.get("request-id")
        otp = confirmation.get("token")
        link_reference_number = confirmation.get("linkRefNumber")

        session = get_link_session(link_reference_number)

        if session is None:
            log_error("Link session not found -- cannot confirm.")
            return

        if not verify_otp(
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

        response = send_on_confirm(
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
