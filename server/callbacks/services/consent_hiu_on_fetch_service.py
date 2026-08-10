from server.callbacks.repository.hiu_consent_repository import save_hiu_consent
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
            # = "manual" in server/config.py).
            maybe_trigger_health_information_request(consent_id, consent_detail)

    except Exception as exc:
        log_error(f"Consent HIU on-fetch callback processing failed unexpectedly: {exc}")
        return
