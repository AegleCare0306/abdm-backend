import json

from server.linking import send_on_init
from server.utils import generate_request_id, generate_expiry_time

async def process_link_init(callback_data):


    body = callback_data["body"]
    headers = callback_data["headers"]

    transaction_id = body.get("transactionId")

    request_id = headers.get("request-id")

    link_reference_number = generate_request_id()

    print("\n===== LINK INIT CALLBACK =====")
    print(json.dumps(callback_data, indent=4))

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