"""
Pluggable trigger for M3 Block 2 (Health Information Request), called
from the end of consent_hiu_on_fetch_service.py's GRANTED success path.

Kept as its own small module (not inlined into consent_hiu_on_fetch_service.py)
so the trigger POLICY (server/config.py's HEALTH_INFORMATION_TRIGGER_MODE)
can change without touching Block 1's own on-fetch logic, and so Block 2
is never hardwired to fire automatically -- per earlier design
discussion, this must stay a deliberate, overridable decision point, not
an unconditional chain reaction off of Block 1 completing.
"""

from server.config import HEALTH_INFORMATION_TRIGGER_MODE
from server.hiu_health_information import initiate_health_information_request
from server.callbacks.utils.flow_logger import log_phase, log_waiting, log_error


def maybe_trigger_health_information_request(consent_id, consent_detail):
    """
    Args:
        consent_id (str): The just-fetched, GRANTED consent artefact's id.
        consent_detail (dict): The consentDetail dict as delivered by the
            on-fetch callback (consent.consentDetail) -- carries hiu.id,
            hip.id, and permission.dateRange, all needed for "auto" mode.

    Branches on HEALTH_INFORMATION_TRIGGER_MODE:
      - "manual" (the current default): no-op. The M3 CLI's own explicit
        Health Information Request flow is the only trigger.
      - "auto": calls initiate_health_information_request() directly,
        using the consent's own approved permission.dateRange as the
        date range.
      - "cache_first": no-op stub, functionally identical to "manual" --
        depends on an unresolved question (Notion To-Do Tracker T-90:
        does re-pulling data on an already-granted consent return fresh
        data?) that hasn't been answered yet, so this deliberately
        doesn't guess at caching behavior that could silently serve
        stale data.

    Never raises -- called from inside consent_hiu_on_fetch_service.py's
    own try/except success path, and a trigger failure here must not be
    mistaken for (or mask) Block 1's own on-fetch outcome, which has
    already fully completed by the time this is called.
    """
    try:
        mode = HEALTH_INFORMATION_TRIGGER_MODE

        if mode == "manual":
            log_phase("HEALTH_INFORMATION_TRIGGER_MODE='manual' -- Block 2 not auto-triggered; use the M3 CLI's Health Information Request flow when ready.")
            return

        if mode == "cache_first":
            log_phase("HEALTH_INFORMATION_TRIGGER_MODE='cache_first' -- not yet implemented (Notion T-90 unresolved), behaving as 'manual'.")
            return

        if mode == "auto":
            hiu_id = (consent_detail.get("hiu") or {}).get("id")
            hip_id = (consent_detail.get("hip") or {}).get("id")
            date_range = (consent_detail.get("permission") or {}).get("dateRange") or {}

            if not hiu_id or not hip_id:
                log_error(f"Cannot auto-trigger Health Information Request for consent {consent_id} -- missing hiu.id/hip.id in consentDetail.")
                return

            log_waiting("HEALTH_INFORMATION_TRIGGER_MODE='auto' -- automatically requesting health information for this consent")

            response = initiate_health_information_request(
                hiu_id=hiu_id,
                consent_id=consent_id,
                hip_id=hip_id,
                date_range_from=date_range.get("from"),
                date_range_to=date_range.get("to"),
            )

            if response.status_code != 202:
                log_error(f"Auto-triggered Health Information Request returned unexpected status {response.status_code}.")
            return

        log_error(f"Unknown HEALTH_INFORMATION_TRIGGER_MODE {mode!r} -- no-op.")

    except Exception as exc:
        log_error(f"maybe_trigger_health_information_request failed unexpectedly: {exc}")
