import json

from server.linking import send_on_init
from server.utils import generate_request_id, generate_expiry_time, print_api_response
from server.callbacks.repository.link_repository import save_link_session
from server.callbacks.repository.patient_identity_repository import get_patient_identity
from server.crypto import encrypt_value, get_public_certificate
from server.abha import request_otp
from server.callbacks.utils.flow_logger import log_phase, log_api_call, log_waiting, log_error


async def process_link_init(callback_data):

    try:
        log_phase("Patient chose to link records -- link request received (POST /api/v3/hip/link/care-context/init)")

        body = callback_data["body"]
        headers = callback_data["headers"]

        abha_address = body.get("abhaAddress")
        transaction_id = body.get("transactionId")
        request_id = headers.get("request-id")
        patient_records= body.get("patient", [])

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

        otp_response = request_otp(
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

        session_data = {
            "transaction_id": transaction_id,
            "request_id": request_id,
            "abha_address": abha_address,
            "selected_patient_records": patient_records,
            "otp_txn_id": otp_txn_id,
        }

        save_link_session(
            link_reference_number,
            session_data
        )

        response = send_on_init(
            transaction_id=transaction_id,
            request_id=request_id,
            link_reference_number=link_reference_number,
            authentication_type="DIRECT",
            communication_medium="MOBILE",
            communication_hint="OTP",
            communication_expiry=generate_expiry_time(),
        )

        log_api_call("Confirming Link Initiated with ABDM", "POST .../on-init", response.status_code)

        if response.status_code != 202:
            print_api_response(response)
            return

        log_waiting("Waiting for the patient to enter the OTP sent to their mobile/email")

    except Exception as exc:
        log_error(f"Link Init callback processing failed unexpectedly: {exc}")
        return
