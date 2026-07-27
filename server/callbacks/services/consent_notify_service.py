from server.healthinformation import send_on_consent_notify
from server.utils import print_api_response


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

    response = send_on_consent_notify(
        consent_id=consent_id,
        request_id=request_id,
    )

    if response.status_code not in (200, 202):
        print_api_response(response)
        return

    print("\nConsent Notify Acknowledged Successfully.")