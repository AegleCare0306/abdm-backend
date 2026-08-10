from server.callbacks.repository.pending_consent_request_repository import get_pending_consent_request, link_consent_request_id
from server.callbacks.utils.flow_logger import log_phase, log_waiting, log_error


async def process_consent_hiu_on_init(callback_data):
    """
    Processes the Consent Init on-init callback (M3 Block 1, step 2).

    Confirmed inbound body shape (Word doc's callback table + a real
    saved Postman example, both agreeing):
        {"consentRequest": {"id": "..."}, "error": null, "response": {"requestId": "..."}}

    Just correlates response.requestId back to the pending session saved
    by initiate_consent_request() (server/hiu_consent.py) and records the
    real consentRequest.id against it, so the later notify callback
    (which arrives keyed by consentRequestId, not our REQUEST-ID) can
    find its way back to this session. No outbound call is made here and
    no further chaining happens -- this just waits for the patient to act
    on the request in their PHR app.
    """
    try:
        log_phase("Consent init acknowledged by ABDM (POST /api/v3/hiu/consent/request/on-init)")

        body = callback_data["body"]
        request_id = (body.get("response") or {}).get("requestId")

        if not request_id:
            log_error("on-init callback missing response.requestId -- cannot correlate to a pending consent request.")
            return

        pending = get_pending_consent_request(request_id)

        if pending is None:
            log_error(f"No pending consent request found for requestId {request_id}.")
            return

        error = body.get("error")
        if error:
            log_error(f"Consent init failed per ABDM: {error}")
            return

        consent_request = body.get("consentRequest") or {}
        consent_request_id = consent_request.get("id")

        if not consent_request_id:
            log_error(f"on-init callback missing consentRequest.id for requestId {request_id}.")
            return

        link_consent_request_id(request_id, consent_request_id)

        log_phase(f"consentRequestId {consent_request_id} recorded for requestId {request_id}")
        log_waiting("Waiting for the patient to act on this consent request in the PHR app")

    except Exception as exc:
        log_error(f"Consent init on-init callback processing failed unexpectedly: {exc}")
        return
