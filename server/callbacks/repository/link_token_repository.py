"""
Repository for temporarily storing pending HIP-Initiated Linking
link token requests.

Current Implementation:
    - Postgres, via server/db.py + server/db_models.py:PendingLinkToken
      (P17, 2026-09-07) -- moved off the prior file-backed
      storage/pending_link_tokens.jsonl. See hiu_consent_repository.py's
      own banner for the full P16/P17 story (why Postgres, why now).
    - Every function's name, signature, and return contract is
      byte-for-byte identical to the file-backed version -- no caller
      outside this file needed to change.

Prior Implementation (superseded, see storage/pending_link_tokens.jsonl --
kept as an inert audit trail, not the live source of truth anymore):
    - File-backed JSON storage (via server/callbacks/utils/json_file_store.py),
      NOT a plain in-memory dict. CHANGED 2026-08-04: an in-memory dict was
      the original implementation, but that made a saved pending session
      invisible across OS process boundaries -- specifically, the M2 test
      CLI (tools/m2_test_suite/cli.py) runs as its own separate process and
      calls generate_link_token() (server/hip_linking.py) directly, which
      is what actually saves a pending session here. The real running
      `uvicorn server.main:app` process -- a different OS process entirely
      -- is what receives ABDM's on-generate-token callback and needs to
      read that same pending session back.
"""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from server.db import session_scope
from server.db_models import PendingLinkToken


def save_pending_link_token(request_id, session_data):
    """
    Saves a pending link token request using the REQUEST-ID sent to ABDM
    as the key. Upsert -- always overwrites any existing row for this
    request_id, same "no merge" contract the file-backed set_key() had.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            generate-token call.
        session_data (dict): Pending link token session information.

    Returns:
        None
    """
    with session_scope() as session:
        stmt = pg_insert(PendingLinkToken).values(request_id=request_id, data=session_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=[PendingLinkToken.request_id],
            set_={"data": stmt.excluded.data, "updated_at": func.now()},
        )
        session.execute(stmt)


def get_pending_link_token(request_id):
    """
    Retrieves a stored pending link token request.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            generate-token call.

    Returns:
        dict | None
    """
    with session_scope() as session:
        row = session.query(PendingLinkToken).filter(PendingLinkToken.request_id == request_id).one_or_none()
        return row.data if row is not None else None


def delete_pending_link_token(request_id):
    """
    Deletes a pending link token request.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            generate-token call.

    Returns:
        bool
    """
    with session_scope() as session:
        deleted = session.query(PendingLinkToken).filter(PendingLinkToken.request_id == request_id).delete()
        return deleted > 0
