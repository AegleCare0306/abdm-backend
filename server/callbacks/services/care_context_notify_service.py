import asyncio

from server.callbacks.repository.care_context_notify_repository import get_pending_care_context_notify, delete_pending_care_context_notify
from server.callbacks.utils.flow_logger import log_phase, log_api_call, log_error

# How long to wait before retrying a real, confirmed ABDM-1006 "No links
# found for the patient in the given HIP" -- a timing race (2026-08-04):
# the auto-triggered Notify call fires ~190ms after Linking Care
# Context's own on_carecontext success callback, which can outrun ABDM's
# backend fully propagating the new link before Notify's own validation
# runs. Two manual retries 24s/40s later for the exact same patient/care
# context both succeeded with no code change -- 5s is a first guess at a
# safe middle ground, not a confirmed ABDM-documented value. Revisit if
# retries still fail at this delay.
_RETRY_DELAY_SECONDS = 5


async def process_care_context_notify(callback_data):

    try:
        log_phase("ABDM acknowledged the care context update notify (POST /api/v3/links/context/on-notify)")

        body = callback_data["body"]

        request_id = body.get("response", {}).get("requestId")
        error = body.get("error")
        acknowledgement = body.get("acknowledgement", {})

        pending = get_pending_care_context_notify(request_id) if request_id else None

        if error:
            log_error(f"Care context update notify failed for requestId {request_id}: {error}")

            code = (error.get("code") or "").strip()

            if code.startswith("ABDM-1006") and pending is not None and pending.get("retry_count", 0) < 1:
                log_phase(
                    f"ABDM-1006 is a known timing race (confirmed 2026-08-04, see "
                    f"care_context_notify_repository.py) -- retrying Notify once after a "
                    f"{_RETRY_DELAY_SECONDS}s delay for care context {pending['care_context_reference']!r}."
                )

                await asyncio.sleep(_RETRY_DELAY_SECONDS)

                # Imported here, not at module level, to avoid a circular
                # import (hip_linking.py imports from this repository
                # module's sibling, care_context_link_repository).
                from server.hip_linking import notify_care_context_update

                try:
                    retry_response = notify_care_context_update(
                        hip_id=pending["hip_id"],
                        abha_address=pending["abha_address"],
                        patient_reference=pending["patient_reference"],
                        care_context_reference=pending["care_context_reference"],
                        hi_types=pending["hi_types"],
                        link_token=pending["link_token"],
                        retry_count=pending.get("retry_count", 0) + 1,
                    )

                    log_api_call(
                        f"Retrying Notify Care Context Update for {pending['care_context_reference']}",
                        "POST .../link/context/notify",
                        retry_response.status_code,
                    )

                except Exception as exc:
                    log_error(f"Retry of Notify Care Context Update failed unexpectedly: {exc}")

            if pending is not None:
                delete_pending_care_context_notify(request_id)

            return

        log_phase(f"Care context update notify acknowledged for requestId {request_id}: {acknowledgement.get('status')}")

        if pending is not None:
            delete_pending_care_context_notify(request_id)

    except Exception as exc:
        log_error(f"Care Context Notify callback processing failed unexpectedly: {exc}")
        return
