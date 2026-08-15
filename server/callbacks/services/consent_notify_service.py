import asyncio

from server.healthinformation import send_on_consent_notify
from server.utils import print_api_response
from server.callbacks.repository.consent_repository import save_consent, delete_consent
from server.callbacks.utils.idempotency import already_processed, mark_processed
from server.callbacks.utils.flow_logger import log_phase, log_api_call, log_waiting, log_error

# Scope name for the idempotency guard below -- see
# server/callbacks/utils/idempotency.py's own docstring for why this
# exists: replaying an old GRANTED consent_notify after a REVOKED one
# arrives in between used to resurrect a deliberately-revoked consent,
# since nothing here could tell "this is the same ABDM message I
# already handled" from "this is a genuinely new notification."
_IDEMPOTENCY_SCOPE = "consent_notify"


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

        # Replay guard: if we've already processed a message carrying
        # this exact REQUEST-ID, this is ABDM retrying (or an attacker
        # replaying) a message we've already acted on -- skip re-running
        # the GRANTED/REVOKED/EXPIRED branch below (which would otherwise
        # e.g. re-save a consent that was legitimately revoked afterward
        # by a *different*, later REQUEST-ID), but still ack ABDM below
        # exactly as if we'd processed it, since from ABDM's perspective
        # this message WAS already handled successfully.
        if already_processed(_IDEMPOTENCY_SCOPE, request_id):
            log_phase(f"REQUEST-ID {request_id} already processed for consent_notify -- treating as a replay, not re-applying consentId={consent_id} status={status}")
            response = await asyncio.to_thread(
                send_on_consent_notify,
                consent_id=consent_id,
                request_id=request_id,
            )
            log_api_call("Acknowledging Consent Notification to ABDM (replay)", "POST .../hip/on-notify", response.status_code)
            if response.status_code != 202:
                print_api_response(response)
            return

        mark_processed(_IDEMPOTENCY_SCOPE, request_id)

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

        # Off the event loop thread -- see discover_service.py's
        # process_discover() for why every blocking requests.* call
        # reachable from an async def callback handler is wrapped this way.
        response = await asyncio.to_thread(
            send_on_consent_notify,
            consent_id=consent_id,
            request_id=request_id,
        )

        log_api_call("Acknowledging Consent Notification to ABDM", "POST .../hip/on-notify", response.status_code)

        if response.status_code != 202:
            print_api_response(response)
            return

        if status == "GRANTED":
            log_waiting("Waiting for the HIU to request the patient's data")

    except Exception as exc:
        log_error(f"Consent Notify callback processing failed unexpectedly: {exc}")
        return
