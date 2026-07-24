import json

from server.linking import send_on_init
from server.utils import generate_request_id, generate_expiry_time
from server.callbacks.repository.link_repository import save_link_session

async def process_link_init(callback_data):
    print("\n===== LINK INIT CALLBACK =====")
    body = callback_data["body"]
    headers = callback_data["headers"]

    abha_address = body.get("abhaAddress")
    transaction_id = body.get("transactionId")
    request_id = headers.get("request-id")
    patient = body.get("patient", [])

    link_reference_number = generate_request_id()

    session_data = {
        "transaction_id": transaction_id,
        "request_id": request_id,
        "abha_address": abha_address,
        "patient": patient
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