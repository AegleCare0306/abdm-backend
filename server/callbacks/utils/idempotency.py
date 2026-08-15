"""
Generic dedup/idempotency guard for inbound ABDM callbacks.

WHY THIS EXISTS: the edge-case review found that no callback handler in
this codebase dedupes a replayed/duplicated inbound message. ABDM's own
gateway retries a callback if it doesn't get a fast enough ack (this
codebase fully processes before returning 200, which invites exactly
that -- see server/callbacks/dispatcher.py's own docstring), and a
REQUEST-ID uniquely identifies one specific outbound message from ABDM's
side -- a genuine retry of the same message reuses the same REQUEST-ID
rather than minting a new one. The most severe concrete case
(edge-case-review M2 case, "M2-9" in the tracker): replaying an old
GRANTED consent_notify AFTER a REVOKED one arrives in between resurrects
a consent that was deliberately revoked, since consent_notify_service.py
had no way to tell "this is the same message I already handled" from
"this is a new, later notification."

This module is a small, reusable primitive (not narrowly written for
just that one case) so the same two functions can be wired into any
other callback handler that needs the same protection -- e.g. the
still-open link_confirm / care_context_notify / link_init duplicate-
callback cases in the test plan (M2-11/M2-12/M2-13) are the same
pattern, but are NOT yet wired to this module (only consent_notify is,
as of this pass) -- do not assume those are fixed just because this
module exists; they still need their own call site added and their own
verification pass.

DESIGN: backed by the same append-only json_file_store.py every other
repository in this codebase uses (survives cross-process/`--reload`
restarts, tolerates a couple of concurrent testers) -- not a new storage
mechanism. Each (scope, request_id) pair is recorded at most once;
already_processed() is a simple presence check.

Deliberately keyed by (scope, request_id) rather than just request_id
alone: ABDM's REQUEST-ID is unique per outbound message, but scoping by
callback type as well avoids any theoretical cross-callback-type
collision and makes storage/processed_callback_request_ids.jsonl
readable on its own (each key visibly says which callback it belongs
to).
"""

from server.callbacks.utils.json_file_store import set_key, get_key

_STORE_FILE = "processed_callback_request_ids.jsonl"


def _composite_key(scope, request_id):
    return f"{scope}:{request_id}"


def already_processed(scope, request_id):
    """
    Returns True if this (scope, request_id) pair has been recorded as
    processed before -- i.e. this inbound callback is a replay/duplicate
    of one already handled, not a new message.

    request_id may be falsy (missing/malformed header) -- treated as
    "not deduped" (returns False) rather than raising, since the calling
    handler already has its own logic for what to do when request_id is
    missing; this module only ever answers "have I seen this exact,
    identified message before."
    """

    if not scope or not request_id:
        return False

    return get_key(_STORE_FILE, _composite_key(scope, request_id)) is not None


def mark_processed(scope, request_id):
    """
    Records that this (scope, request_id) pair has now been processed.
    Call this once the handler has decided it will act on the message
    (not necessarily only after every side effect succeeds -- matching
    every other callback handler in this codebase, which acks ABDM
    regardless of internal processing outcome; see dispatcher.py). A
    no-op if request_id is falsy.
    """

    if not scope or not request_id:
        return

    set_key(_STORE_FILE, _composite_key(scope, request_id), True)
