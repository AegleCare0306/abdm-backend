"""
Repository for temporarily storing a pending Notify Care Context Update
request, so its on-notify callback (M2 doc §4.3.7) can retry the call
once if ABDM returns ABDM-1006 ("No links found for the patient in the
given HIP") -- a real, confirmed timing race (2026-08-04): the auto
Notify call fires ~190ms after Linking Care Context's own on_carecontext
success callback, which can be faster than ABDM's backend fully
propagating the new link before Notify's own validation runs. Two
manual retries 24s/40s later for the exact same patient/care context
both succeeded with no code change, supporting a timing explanation
over a data/logic bug.

The on-notify callback body only carries {requestId, timestamp,
acknowledgement, response.requestId, error} -- it does NOT echo back
what was actually notified, so that has to be stashed here before the
outbound notify_care_context_update() call and read back if a retry is
needed.

Current Implementation:
    - Postgres, via server/db.py + server/db_models.py:PendingCareContextNotify
      (P17, 2026-09-07) -- moved off the prior file-backed
      storage/pending_care_context_notifies.jsonl. See
      hiu_consent_repository.py's own banner for the full P16/P17 story.
    - Every function's name, signature, and return contract is
      byte-for-byte identical to the file-backed version -- no caller
      outside this file needed to change.

Prior Implementation (superseded, see storage/pending_care_context_notifies.jsonl
-- kept as an inert audit trail, not the live source of truth anymore):
    - File-backed JSON storage (via server/callbacks/utils/json_file_store.py),
      same pattern as the other pending-session stores in this codebase.
"""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from server.db import session_scope
from server.db_models import PendingCareContextNotify


def save_pending_care_context_notify(request_id, session_data):
    """
    Saves a pending Notify Care Context Update request using the
    REQUEST-ID sent to ABDM as the key. Upsert -- always overwrites any
    existing row for this request_id, same "no merge" contract the
    file-backed set_key() had.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            link/context/notify call.
        session_data (dict): hip_id, abha_address, patient_reference,
            care_context_reference, hi_types, link_token, retry_count.

    Returns:
        None
    """
    with session_scope() as session:
        stmt = pg_insert(PendingCareContextNotify).values(request_id=request_id, data=session_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=[PendingCareContextNotify.request_id],
            set_={"data": stmt.excluded.data, "updated_at": func.now()},
        )
        session.execute(stmt)


def get_pending_care_context_notify(request_id):
    """
    Retrieves a stored pending Notify Care Context Update request.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            link/context/notify call.

    Returns:
        dict | None
    """
    with session_scope() as session:
        row = (
            session.query(PendingCareContextNotify)
            .filter(PendingCareContextNotify.request_id == request_id)
            .one_or_none()
        )
        return row.data if row is not None else None


def delete_pending_care_context_notify(request_id):
    """
    Deletes a pending Notify Care Context Update request.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            link/context/notify call.

    Returns:
        bool
    """
    with session_scope() as session:
        deleted = (
            session.query(PendingCareContextNotify)
            .filter(PendingCareContextNotify.request_id == request_id)
            .delete()
        )
        return deleted > 0
