from server.healthinformation import send_on_consent_notify
from server.utils import print_api_response
from server.callbacks.repository.consent_repository import save_consent, delete_consent
from server.callbacks.utils.flow_logger import log_phase, log_api_call, log_waiting, log_error


async def process_consent_notify(
    callback_data,
):
    """
    Processes the Consent Notify callback.
    """
    try:
        log_phase("Consent status update received from ABDM (POST /api/v3/consent/request/hip/notify)")

        headers = callback_data["headers"]
        body = callback_data["body"]
        request_id = headers.get("request-id")
        notification = body.get("notification")
        consent_id = notification.get("consentId") if notification is not None else None

        if notification is None or consent_id is None:
            log_error("Consent notification payload missing 'notification' or 'consentId' -- cannot process.")
            return

        status = notification.get("status")

        log_phase(f"Extracted consent ID and status ({status})")

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

            log_phase("Consent granted -- storing approved care contexts")

        elif status in ("REVOKED", "EXPIRED"):

            delete_consent(consent_id)

            log_phase(f"Consent {status.lower()} -- removed stored consent artifact for consentId={consent_id}")

        else:

            log_phase(f"Consent notification status='{status}' -- not storing (only GRANTED consents carry a usable artifact)")

        response = send_on_consent_notify(
            consent_id=consent_id,
            request_id=request_id,
        )

        log_api_call("Acknowledging Consent Notification to ABDM", "POST .../hip/on-notify", response.status_code)

        if response.status_code not in (200, 202):
            print_api_response(response)
            return

        if status == "GRANTED":
            log_waiting("Waiting for the HIU to request the patient's data")

    except Exception as exc:
        log_error(f"Consent Notify callback processing failed unexpectedly: {exc}")
        return
