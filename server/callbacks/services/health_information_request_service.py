import json

from server.callbacks.repository.health_information_repository import save_health_information_session
from server.callbacks.repository.consent_repository import get_consent
from server.callbacks.services.health_information_data_service import build_bundles_for_care_contexts
from server.healthinformation import send_on_health_information_request
from server.utils import print_api_response

async def process_health_information_request(
    callback_data,
):

    print("\n===== HEALTH INFORMATION REQUEST CALLBACK =====")

    headers = callback_data["headers"]
    body = callback_data["body"]

    request_id = headers.get("request-id")
    hip_id = headers.get("x-hip-id")
    transaction_id = body.get("transactionId")

    hi_request = body.get("hiRequest",{})
    consent_id = (hi_request.get("consent", {}).get("id"))
    date_range = hi_request.get("dateRange",{})
    data_push_url = hi_request.get("dataPushUrl")
    key_material = hi_request.get("keyMaterial",{})

    consent = get_consent(consent_id)

    care_context_references = []
    fhir_bundles = None

    if consent is None:
        print(f"No stored consent artifact found for consentId={consent_id} -- cannot build records (was it ever GRANTED?).")
    else:
        care_context_references = [
            care_context.get("careContextReference")
            for care_context in consent.get("care_contexts", [])
            if care_context.get("careContextReference")
        ]
        fhir_bundles = build_bundles_for_care_contexts(care_context_references)
        print(f"Built {len(fhir_bundles)} FHIR bundle(s) for {len(care_context_references)} consented care context(s).")

    session_data = {
        "request_id": request_id,
        "transaction_id": transaction_id,
        "hip_id": hip_id,
        "consent_id": consent_id,
        "care_context_references": care_context_references,
        "date_range": date_range,
        "data_push_url": data_push_url,
        "key_material": key_material,

        "body": body,

        "records": None,
        "fhir_bundles": fhir_bundles,
        "encrypted_bundle": None,
        "checksum": None,
        "transfer_status": None,
    }

    save_health_information_session(
        transaction_id,
        session_data,
    )

    print(json.dumps(
        session_data,
        indent=4,
    ))

    response = send_on_health_information_request(
        transaction_id=transaction_id,
        request_id=request_id,
    )

    if response.status_code not in (200, 202):
        print_api_response(response)
        return

    print("\nHealth Information Request Acknowledged Successfully.")