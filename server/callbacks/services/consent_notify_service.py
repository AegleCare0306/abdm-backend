from server.healthinformation import send_on_consent_notify
from server.utils import print_api_response
from server.callbacks.repository.consent_repository import save_consent


async def process_consent_notify(
    callback_data,
):
    """
    Processes the Consent Notify callback.
    """
    print("\n===== CONSENT NOTIFY CALLBACK =====")

    headers = callback_data["headers"]
    body = callback_data["body"]
    request_id = headers.get("request-id")
    notification = body["notification"]
    consent_id = notification["consentId"]
    status = notification.get("status")

    if status == "GRANTED":

        consent_detail = notification.get("consentDetail", {})

        save_consent(
            consent_id,
            {
                "patient_id": consent_detail.get("patient", {}).get("id"),
                "care_contexts": consent_detail.get("careContexts", []),
                "hi_types": consent_detail.get("hiTypes", []),
                "date_range": consent_detail.get("permission", {}).get("dateRange", {}),
                "hip_id": consent_detail.get("hip", {}).get("id"),
            },
        )

        print(f"Stored granted consent artifact for consentId={consent_id}")

    else:

        print(f"Consent notification status='{status}' -- not storing (only GRANTED consents carry a usable artifact)")

    response = send_on_consent_notify(
        consent_id=consent_id,
        request_id=request_id,
    )

    if response.status_code not in (200, 202):
        print_api_response(response)
        return

    print("\nConsent Notify Acknowledged Successfully.")