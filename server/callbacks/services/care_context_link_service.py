import asyncio

from server.callbacks.repository.care_context_link_repository import get_pending_care_context_link, delete_pending_care_context_link, save_pending_care_context_link
from server.hip_linking import notify_care_context_update
from server.callbacks.utils.idempotency import already_processed, mark_processed
from server.callbacks.utils.flow_logger import log_phase, log_api_call, log_error

# See server/callbacks/utils/idempotency.py's own docstring, and
# consent_notify_service.py's use of the same pattern (tracker case
# M2-9) -- this closes the sibling case M2-12 ("sending the same 'care
# context linked' message twice roughly doubles the notifications
# sent"). On a detected replay this skips the whole per-care-context
# Notify Care Context Update loop below rather than re-firing it --
# UNLESS a prior attempt left some care contexts still pending after a
# permanent per-call failure, in which case the replay is used to retry
# just those (see M2-56 fix below).
_IDEMPOTENCY_SCOPE = "care_context_link"


async def process_care_context_link(callback_data):

    try:
        log_phase("ABDM confirmed the care context link result (POST /api/v3/link/on_carecontext)")

        body = callback_data["body"]

        abha_address = body.get("abhaAddress")
        status = body.get("status")
        error = body.get("error")
        request_id = body.get("response", {}).get("requestId")

        if already_processed(_IDEMPOTENCY_SCOPE, request_id):
            # RETRY-EXHAUSTION GUARD (tracker case M2-56): the OLD code
            # unconditionally treated any replay as a true no-op duplicate
            # and returned immediately. But a FIRST delivery that only
            # partially succeeded (some Notify Care Context Update calls
            # permanently failed even after call_with_retry's own retries
            # -- see the loop below) leaves the still-failed care contexts
            # in the pending record instead of deleting it outright, so a
            # replay of this same on_carecontext message isn't necessarily
            # a genuine duplicate to skip -- it may be exactly the retry
            # opportunity needed to finish notifying the ones that didn't
            # go through the first time. Check for leftover pending work
            # before deciding this is a true no-op.
            pending_retry = get_pending_care_context_link(request_id)

            if pending_retry is None:
                log_phase(f"REQUEST-ID {request_id} already processed for care_context_link -- treating as a replay, skipping (every care context was already notified successfully).")
                return

            log_phase(
                f"REQUEST-ID {request_id} already processed for care_context_link, but "
                f"{len(pending_retry['care_context_hi_types'])} care context(s) are still "
                f"pending from a prior partial failure -- retrying just those instead of "
                f"treating this as a pure no-op replay."
            )
            await _notify_pending_care_contexts(
                request_id,
                pending_retry,
                abha_address or pending_retry["abha_address"],
            )
            return

        mark_processed(_IDEMPOTENCY_SCOPE, request_id)

        pending = get_pending_care_context_link(request_id) if request_id else None

        if error:
            log_error(f"Care context linking failed for {abha_address}: {error}")

            if pending is not None:
                delete_pending_care_context_link(request_id)

            return

        log_phase(f"Care context successfully linked for {abha_address}: {status}")

        # Step 3 of the chain (M2 doc §4.3.6): auto-trigger Notify Care
        # Context Update for every care context that was just linked,
        # since on_carecontext's own body doesn't say which ones those
        # were -- that's what link_care_context() stashed here before
        # its outbound call (see hip_linking.py's _invert_for_notify()).
        if pending is None:
            log_error(
                f"No pending care context link session found for requestId {request_id!r} "
                f"-- skipping auto-triggered Notify Care Context Update."
            )
            return

        resolved_abha_address = abha_address or pending["abha_address"]

        await _notify_pending_care_contexts(request_id, pending, resolved_abha_address)

    except Exception as exc:
        log_error(f"Care Context Link callback processing failed unexpectedly: {exc}")
        return


async def _notify_pending_care_contexts(request_id, pending, resolved_abha_address):
    """
    Runs the per-care-context Notify Care Context Update loop against
    whatever's in `pending["care_context_hi_types"]`, then reconciles the
    stored pending record based on the outcome (tracker case M2-56):

    - Every care context notified successfully (202) -> the pending
      record is deleted, same as before this fix.
    - One or more permanently failed (a non-202 status, or an exception
      that survived call_with_retry's own retries) -> the pending record
      is REWRITTEN to contain only the still-failed subset, rather than
      being deleted. This is what lets a future replay of the same
      on_carecontext message (see the already_processed() branch above)
      retry just the leftovers instead of the failure being silently
      permanent -- the OLD code deleted the pending record unconditionally
      after this loop, regardless of individual failures within it, so a
      permanently-failed notify call had no recovery path at all, even on
      a genuine ABDM redelivery of the same message.
    """

    still_failed = {}

    for care_context_reference, hi_types in pending["care_context_hi_types"].items():

        try:
            # Off the event loop thread -- see discover_service.py's
            # process_discover() for why every blocking requests.*
            # call reachable from an async def callback handler is
            # wrapped this way. This runs once per care context in
            # the loop, sequentially -- each await still only blocks
            # this one request's own handling, never the shared loop.
            notify_response = await asyncio.to_thread(
                notify_care_context_update,
                hip_id=pending["hip_id"],
                abha_address=resolved_abha_address,
                patient_reference=pending["patient_reference"],
                care_context_reference=care_context_reference,
                hi_types=hi_types,
                link_token=pending["link_token"],
            )

            log_api_call(
                f"Notifying care context update for {care_context_reference}",
                "POST .../link/context/notify",
                notify_response.status_code,
            )

            if notify_response.status_code != 202:
                log_error(
                    f"Notify Care Context Update for {care_context_reference} returned "
                    f"unexpected status {notify_response.status_code} -- keeping it pending "
                    f"for a future retry rather than dropping it."
                )
                still_failed[care_context_reference] = hi_types

        except Exception as exc:
            # One failed Notify call (network error or otherwise) must
            # not stop the rest -- each care context is independent.
            log_error(f"Notify Care Context Update for {care_context_reference} failed unexpectedly: {exc} -- keeping it pending for a future retry rather than dropping it.")
            still_failed[care_context_reference] = hi_types

    if still_failed:
        updated_pending = dict(pending)
        updated_pending["care_context_hi_types"] = still_failed
        save_pending_care_context_link(request_id, updated_pending)
        log_error(
            f"{len(still_failed)} of {len(pending['care_context_hi_types'])} care context(s) "
            f"still failed to notify for requestId {request_id!r} -- kept pending, not deleted, "
            f"so a future redelivery of this on_carecontext message can retry them."
        )
    else:
        delete_pending_care_context_link(request_id)
