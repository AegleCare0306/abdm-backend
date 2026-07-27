from server.callbacks.repository.link_repository import get_link_session
from server.callbacks.repository.patient_repository import search_patient
from server.callbacks.transformers.patient_transformer import build_patient_payload
from server.callbacks.services.otp_service import verify_otp
from server.linking import send_on_confirm
from server.utils import print_api_response
from server.callbacks.repository.patient_identity_repository import get_patient_identity


async def process_link_confirm(callback_data):

    print("\n===== CONFIRM CALLBACK =====")

    headers = callback_data["headers"]
    body = callback_data["body"]
    confirmation = body.get("confirmation", {})

    request_id = headers.get("request-id")
    otp = confirmation.get("token")
    link_reference_number = confirmation.get("linkRefNumber")

    # ---------------------------------------------------------
    # Retrieve Link Session
    # ---------------------------------------------------------

    session = get_link_session(link_reference_number)

    if session is None:
        print("Link session not found.")
        return

    # ---------------------------------------------------------
    # Verify OTP
    # ---------------------------------------------------------

    if not verify_otp(
            otp=otp,
            txn_id=session["otp_txn_id"],
    ):
        return

    # ---------------------------------------------------------
    # Search Patient Records
    # ---------------------------------------------------------
    patient = get_patient_identity(
        session["abha_address"]
    )

    records = search_patient(
    abha_address=session["abha_address"],
    hip_id=patient["hip_id"],
    patient_selection=session["selected_patient_records"])
    # ---------------------------------------------------------
    # Build ABDM Patient Payload
    # ---------------------------------------------------------

    patient_payload = build_patient_payload(records)

    # ---------------------------------------------------------
    # Send on-confirm
    # ---------------------------------------------------------

    response = send_on_confirm(
        patient=patient_payload,
        request_id=request_id,
    )

    print("on-confirm response sent successfully.")

    print("\n===== ON CONFIRM RESPONSE =====")
    print(f"Status Code : {response.status_code}")

    if response.status_code != 202:
        print_api_response(response)