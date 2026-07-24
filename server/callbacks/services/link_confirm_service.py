from server.callbacks.repository.patient_repository import search_patient
from server.callbacks.transformers.patient_transformer import build_patient_payload
from server.linking import send_on_confirm
from server.utils import print_api_response
from server.callbacks.services.otp_service import verify_otp
from server.callbacks.repository.link_repository import get_link_session

import json

async def process_link_confirm(callback_data):

    print("\n===== CONFIRM CALLBACK =====")
    headers = callback_data["headers"]
    body = callback_data["body"]
    confirmation = body.get("confirmation", {})

    request_id = headers.get("request-id")
    otp = confirmation.get("token")
    link_reference_number = confirmation.get("linkRefNumber")

    session = get_link_session(link_reference_number)

    if not verify_otp(otp):
        return

    payload = {
        "patient": session["patient"],
        "response": {
            "requestId": request_id
        }
    }

    response = send_on_confirm(
        patient=session["patient"],
        request_id=request_id
    )

    print("\n===== ON CONFIRM RESPONSE =====")
    print(f"Status Code : {response.status_code}")

    if response.status_code != 202:
        print_api_response(response)