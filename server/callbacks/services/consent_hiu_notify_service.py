import asyncio

from server.hiu_consent import fetch_consent, send_consent_hiu_on_notify
from server.utils import print_api_response
from server.callbacks.repository.pending_consent_request_repository import get_pending_consent_request_by_consent_request_id
from server.callbacks.repository.hiu_consent_repository import delete_hiu_consent
from server.callbacks.utils.flow_logger import log_phase, log_api_call, log_waiting, log_error


async def process_consent_hiu_notify(callback_data):
    """
    Processes the HIU Consent Notify callback (M3 Block 1, step 3).

    Confirmed inbound body shape (Word doc's callback table, not
    guessed):
        {"notification": {"consentRequestId": "...", "status": "GRANTED",
         "reason": null, "consentArtefacts": [{"id": "..."}]}}
    Confirmed inbound headers: REQUEST-ID, TIMESTAMP, X-HIU-ID.

    Genuinely a different endpoint from M2's HIP-side consent notify
    (server/callbacks/services/consent_notify_service.py) -- different
    route, different payload shape (consentRequestId + a
    consentArtefacts array here, vs a single consentId + consentDetail
    there) -- so this does NOT import from or reuse that file, per this
    pass's scope.

    If status == "GRANTED", calls fetch_consent() (server/hiu_consent.py)
    once per entry in consentArtefacts (there can be more than one --
    a multi-HIP grant), then acknowledges via send_consent_hiu_on_notify()
    with one {"status", "consentId"} entry per artefact -- the ack's
    consentId values come from consentArtefacts[].id, since this payload
    has no top-level consentId field. For any other status (DENIED,
    REVOKED, etc.), no fetch is triggered -- this just logs and still
    acks with whatever artefacts (if any) were present.
    """
    try:
        log_phase("Consent status notification received from ABDM (POST /api/v3/hiu/consent/request/notify)")

        headers = callback_data["headers"]
        body = callback_data["body"]
        request_id = headers.get("request-id")

        notification = body.get("notification")
        consent_request_id = notification.get("consentRequestId") if notification is not None else None

        if notification is None or not consent_request_id:
            log_error("Consent notification payload missing 'notification' or 'consentRequestId' -- cannot process.")
            return

        status = notification.get("status")
        consent_artefacts = notification.get("consentArtefacts") or []

        log_phase(f"Extracted consentRequestId and status ({status}) -- {len(consent_artefacts)} artefact(s)")

        pending = get_pending_consent_request_by_consent_request_id(consent_request_id)

        if pending is None:
            log_error(f"No pending consent request found for consentRequestId {consent_request_id} -- cannot resolve our hiu_id.")

        hiu_id = pending.get("hiu_id") if pending else None

        if status == "GRANTED":
            if hiu_id is None:
                log_error(f"Skipping fetch_consent() for {len(consent_artefacts)} artefact(s) -- no hiu_id resolved for consentRequestId {consent_request_id}.")
            else:
                # PER-ARTEFACT ERROR ISOLATION (edge-case-review pass,
                # tracker case M3-26): before this fix, a network failure
                # on fetch_consent() for ANY one artefact in a multi-HIP
                # grant (this loop -- one entry per hospital) raised
                # straight out of this loop with no try/except of its own,
                # which meant the exception propagated all the way to this
                # function's OUTER try/except, which just logs and
                # returns -- WITHOUT ever reaching the
                # send_consent_hiu_on_notify() ack below. That doesn't
                # just fail the one artefact whose fetch call hit the
                # hiccup: it silently drops the ack for EVERY artefact in
                # this notification, including ones whose fetch_consent()
                # call already succeeded moments earlier in the same loop
                # (that side effect already happened and can't be undone,
                # but ABDM is never told about it) and ones later in the
                # list that never even got a chance to run. From ABDM's
                # perspective the entire multi-hospital consent grant
                # looks like it was never received at all. Fixed by
                # wrapping each artefact's own fetch_consent() call in its
                # own try/except: one artefact's failure is logged and
                # skipped, every other artefact in the same notification
                # still gets its fetch attempted, and the ack step below
                # always runs afterward for whichever artefacts have an
                # id, regardless of how any individual fetch went.
                for artefact in consent_artefacts:
                    consent_id = artefact.get("id")
                    if not consent_id:
                        continue
                    try:
                        # Off the event loop thread -- see discover_service.py's
                        # process_discover() for why every blocking requests.*
                        # call reachable from an async def callback handler is
                        # wrapped this way. Runs once per artefact in the loop,
                        # sequentially.
                        response = await asyncio.to_thread(fetch_consent, hiu_id=hiu_id, consent_id=consent_id)
                        log_api_call(f"Fetching granted consent artefact {consent_id}", "POST .../consent/v3/fetch", response.status_code)
                        if response.status_code != 202:
                            print_api_response(response)
                    except Exception as exc:
                        log_error(f"fetch_consent() failed for artefact {consent_id} (consentRequestId {consent_request_id}): {exc} -- continuing with the remaining artefact(s) in this notification.")
                log_phase("Consent granted -- fetch attempted for each artefact")
        elif status in ("REVOKED", "EXPIRED"):
            # BUG FIX (Aayush, reported live via the M3 CLI, 2026-09-02):
            # "even though I revoked the consent I still get an option to
            # request data from that consent." Root cause: this branch
            # used to just log and never touched hiu_consent_repository,
            # so an artefact's locally cached copy (saved once, at
            # on-fetch time, by consent_hiu_on_fetch_service.py) kept
            # reading status="GRANTED" forever, even after ABDM notified
            # us the patient revoked it. select_granted_consent()
            # (tools/m3_test_suite/common.py) filters its own picker on
            # exactly that stored field, so a revoked consent kept
            # showing up there as if still active. Mirrors the M2/HIP-
            # side handling of this same status pair already established
            # in consent_notify_service.py's process_consent_notify()
            # (delete_consent() on REVOKED/EXPIRED) -- delete_hiu_consent()
            # already existed in hiu_consent_repository.py for exactly
            # this, but was never actually called from anywhere until now.
            for artefact in consent_artefacts:
                consent_id = artefact.get("id")
                if not consent_id:
                    continue
                if delete_hiu_consent(consent_id):
                    log_phase(f"Consent {status.lower()} -- removed stored HIU consent artefact for consentId={consent_id}")
        else:
            log_phase(f"Consent notification status='{status}' -- not fetching (only GRANTED artefacts are fetched)")

        acknowledgements = [
            {"status": "OK", "consentId": artefact.get("id")}
            for artefact in consent_artefacts
            if artefact.get("id")
        ]

        response = await asyncio.to_thread(
            send_consent_hiu_on_notify,
            acknowledgements=acknowledgements,
            request_id=request_id,
        )

        log_api_call("Acknowledging Consent Notification to ABDM", "POST .../hiu/on-notify", response.status_code)

        if response.status_code != 202:
            print_api_response(response)
            return

        if status == "GRANTED":
            log_waiting("Waiting for ABDM's on-fetch callback with full consent detail")

    except Exception as exc:
        log_error(f"Consent HIU Notify callback processing failed unexpectedly: {exc}")
        return
