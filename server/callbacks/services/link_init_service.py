import json

from server.linking import send_on_init
from server.utils import generate_request_id, generate_expiry_time
from server.callbacks.repository.link_repository import save_link_session
from server.callbacks.repository.patient_identity_repository import get_patient_identity
from server.crypto import encrypt_value, get_public_certificate
from server.abha import request_otp


async def process_link_init(callback_data):
    print("\n===== LINK INIT CALLBACK =====")
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
        print("Patient identity not found.")
        return

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

    print("\n===== LINK INIT CALLBACK =====")

    response = send_on_init(
        transaction_id=transaction_id,
        request_id=request_id,
        link_reference_number=link_reference_number,
        authentication_type="DIRECT",
        communication_medium="MOBILE",
        communication_hint="OTP",
        communication_expiry=generate_expiry_time(),
    )

    print("\n===== ON INIT RESPONSE =====")
    print(f"Status Code : {response.status_code}")

    if response.status_code != 202:
        print_api_response(response)