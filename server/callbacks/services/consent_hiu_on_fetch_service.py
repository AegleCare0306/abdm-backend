import asyncio

from server.callbacks.repository.hiu_consent_repository import save_hiu_consent
from server.callbacks.repository.pending_consent_request_repository import get_pending_consent_request
from server.callbacks.services.health_information_trigger import maybe_trigger_health_information_request
from server.callbacks.utils.flow_logger import log_phase, log_error


async def process_consent_hiu_on_fetch(callback_data):
    """
    Processes the HIU Consent on-fetch callback (M3 Block 1's final
    step).

    Confirmed inbound body shape (Word doc's callback table and a real
    captured Postman example, matching field-for-field):
        {"consent": {"status": "...", "consentDetail": {...}, "signature": "..."},
         "error": null, "response": {"requestId": "..."}}

    Stores the full consentDetail (plus signature) into
    hiu_consent_repository, keyed by consent.consentDetail.consentId.
    Nothing else happens after this -- Block 1 ends here.

    CORRELATION CHECK (added in the edge-case-review pass, tracker case
    M3-10): before this fix, any caller of this route was accepted
    unconditionally -- a completely made-up consentId, never actually
    granted or fetched by us, would be stored as if it were real. The
    route itself now requires a validly ABDM-signed bearer JWT (see
    server/callbacks/utils/jwt_auth.py, tracker case M2-19/M3-17), which
    already blocks the CRITICAL "any outside stranger" scenario the doc
    described -- but that alone doesn't stop a callback for a consentId
    we never actually initiated a fetch for. response.requestId is our
    own REQUEST-ID, echoed back from the fetch_consent() call that
    started this (server/hiu_consent.py) -- fetch_consent() stashes a
    pending session under that same REQUEST-ID with the consent_id it
    requested (save_pending_consent_request()) before making the call.
    Cross-checking both here closes the residual gap: we only accept an
    on-fetch callback that actually correlates back to a fetch we
    ourselves made, for the same consentId.
    """
    try:
        log_phase("Full consent artefact received from ABDM (POST /api/v3/hiu/consent/on-fetch)")

        body = callback_data["body"]

        error = body.get("error")
        if error:
            log_error(f"Consent fetch failed per ABDM: {error}")
            return

        consent = body.get("consent") or {}
        consent_detail = consent.get("consentDetail") or {}
        consent_id = consent_detail.get("consentId")

        if not consent_id:
            log_error("on-fetch callback missing consent.consentDetail.consentId -- cannot store.")
            return

        request_id = (body.get("response") or {}).get("requestId")
        pending = get_pending_consent_request(request_id) if request_id else None

        if pending is None:
            log_error(f"on-fetch callback for consentId={consent_id} has no matching pending fetch (requestId={request_id!r}) -- rejecting, not storing.")
            return

        if pending.get("consent_id") != consent_id:
            log_error(f"on-fetch callback consentId={consent_id} does not match the consentId={pending.get('consent_id')!r} we actually requested for requestId={request_id} -- rejecting, not storing.")
            return

        save_hiu_consent(
            consent_id,
            {
                "status": consent.get("status"),
                "consent_detail": consent_detail,
                "signature": consent.get("signature"),
            },
        )

        log_phase(f"Consent artefact {consent_id} stored -- Block 1 complete for this consent.")

        if consent.get("status") == "GRANTED":
            # Pluggable, not hardwired -- see health_information_trigger.py's
            # own docstring. Defaults to a no-op (HEALTH_INFORMATION_TRIGGER_MODE
            # = "manual" in server/config.py) -- but when set to "auto",
            # maybe_trigger_health_information_request() (itself a plain
            # synchronous function, like _push_and_notify() in
            # health_information_request_service.py) internally calls
            # initiate_health_information_request(), a blocking
            # requests.post(). Wrapped as one whole unit here for the same
            # reason as that other special case: off the event loop
            # thread, without needing to make the trigger module itself
            # async or split its internal call out separately. Currently
            # dormant (mode="manual" today) but in scope, since a mode
            # change alone must not silently reintroduce this pass's
            # deadlock risk.
            await asyncio.to_thread(maybe_trigger_health_information_request, consent_id, consent_detail)

    except Exception as exc:
        log_error(f"Consent HIU on-fetch callback processing failed unexpectedly: {exc}")
        return
