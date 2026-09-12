"""
Repository for temporarily storing a pending Linking Care Context
request, so its on_carecontext callback (M2 doc §4.3.4) can auto-trigger
step 3 of the chain -- Notify Care Context Update (§4.3.6) -- for every
care context that was just linked.

The on_carecontext callback body only carries {abhaAddress, status,
error, response.requestId} -- it does NOT echo back which care contexts
were submitted, so that has to be stashed here before the outbound
link_care_context() call and read back once the callback confirms
success.

Current Implementation:
    - Postgres, via server/db.py + server/db_models.py:PendingCareContextLink
      (P17, 2026-09-07) -- moved off the prior file-backed
      storage/pending_care_context_links.jsonl. See
      hiu_consent_repository.py's own banner for the full P16/P17 story
      (why Postgres, why now).
    - Every function's name, signature, and return contract is
      byte-for-byte identical to the file-backed version -- no caller
      outside this file needed to change.

Prior Implementation (superseded, see storage/pending_care_context_links.jsonl
-- kept as an inert audit trail, not the live source of truth anymore):
    - File-backed JSON storage (via server/callbacks/utils/json_file_store.py),
      NOT a plain in-memory dict -- link_care_context() is called from two
      different OS processes (the auto-chained path inside the running
      `uvicorn server.main:app` process, and the M2 test CLI's reuse-token
      path as its own separate process), and whichever process receives
      ABDM's on_carecontext callback needs to read back whatever was
      saved, regardless of which process did the saving.
"""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from server.db import session_scope
from server.db_models import PendingCareContextLink


def save_pending_care_context_link(request_id, session_data):
    """
    Saves a pending Linking Care Context request using the REQUEST-ID
    sent to ABDM as the key. Upsert -- always overwrites any existing row
    for this request_id, same "no merge" contract the file-backed
    set_key() had.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            link/carecontext call.
        session_data (dict): Pending care context link session
            information -- hip_id, abha_address, link_token,
            patient_reference, and care_context_hi_types (a
            {care_context_reference: [hi_type, ...]} map).

    Returns:
        None
    """
    with session_scope() as session:
        stmt = pg_insert(PendingCareContextLink).values(request_id=request_id, data=session_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=[PendingCareContextLink.request_id],
            set_={"data": stmt.excluded.data, "updated_at": func.now()},
        )
        session.execute(stmt)


def get_pending_care_context_link(request_id):
    """
    Retrieves a stored pending care context link request.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            link/carecontext call.

    Returns:
        dict | None
    """
    with session_scope() as session:
        row = (
            session.query(PendingCareContextLink)
            .filter(PendingCareContextLink.request_id == request_id)
            .one_or_none()
        )
        return row.data if row is not None else None


def delete_pending_care_context_link(request_id):
    """
    Deletes a pending care context link request.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            link/carecontext call.

    Returns:
        bool
    """
    with session_scope() as session:
        deleted = (
            session.query(PendingCareContextLink)
            .filter(PendingCareContextLink.request_id == request_id)
            .delete()
        )
        return deleted > 0
