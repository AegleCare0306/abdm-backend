"""
Repository for temporarily storing ABDM Care Context linking sessions
(UIL's Link Init -> Link Confirm chain), keyed by link_reference_number.

Current Implementation:
    - Postgres, via server/db.py + server/db_models.py:LinkSession (P17,
      2026-09-07) -- moved off the prior file-backed
      storage/link_sessions.jsonl. See hiu_consent_repository.py's own
      banner for the full P16/P17 story (why Postgres, why now).
    - Every function's name, signature, and return contract is
      byte-for-byte identical to the file-backed version -- no caller
      outside this file needed to change.
    - clear_all_link_sessions() is now a REAL bulk DELETE, not a loop of
      tombstone-appends -- the "no true truncate" limitation it worked
      around (see the file-backed version's own docstring) doesn't apply
      to a real table.

Prior Implementation (superseded, see storage/link_sessions.jsonl -- kept
as an inert audit trail, not the live source of truth anymore):
    - File-backed, append-only JSON log -- CHANGED 2026-08-05, was a plain
      in-memory dict (T-80 on the To-Do Tracker). Same reasons as every
      other repository converted this way: a link session saved by one
      server process (e.g. before a `--reload` restart) was invisible to
      a later process, even though the gap between Link Init and Link
      Confirm "can be seconds or days" per the M2 flow docs.
"""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from server.db import session_scope
from server.db_models import LinkSession


# -----------------------------------------------------------------------------
# Save Link Session
# -----------------------------------------------------------------------------

def save_link_session(link_reference_number, session_data):
    """
    Saves a link session using the link reference number as the key.
    Upsert -- always overwrites any existing row for this
    link_reference_number, same "no merge" contract the file-backed
    set_key() had.

    Args:
        link_reference_number (str): ABDM Link Reference Number.
        session_data (dict): Link session information.

    Returns:
        None
    """
    with session_scope() as session:
        stmt = pg_insert(LinkSession).values(link_reference_number=link_reference_number, data=session_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=[LinkSession.link_reference_number],
            set_={"data": stmt.excluded.data, "updated_at": func.now()},
        )
        session.execute(stmt)


# -----------------------------------------------------------------------------
# Get Link Session
# -----------------------------------------------------------------------------

def get_link_session(link_reference_number):
    """
    Retrieves a stored link session.

    Args:
        link_reference_number (str): ABDM Link Reference Number.

    Returns:
        dict | None
    """
    with session_scope() as session:
        row = (
            session.query(LinkSession)
            .filter(LinkSession.link_reference_number == link_reference_number)
            .one_or_none()
        )
        return row.data if row is not None else None


# -----------------------------------------------------------------------------
# Update Link Session
# -----------------------------------------------------------------------------

def update_link_session(link_reference_number, updated_data):
    """
    Updates an existing link session -- a FULL REPLACE of the stored
    dict with `dict(session).update(updated_data)`'s own result (matching
    the file-backed version's own read-modify-write exactly: a shallow
    Python dict.update() merge computed in Python, then written as one
    new value -- NOT a partial JSONB merge done in SQL). Returns False
    without writing anything if the session doesn't currently exist.

    Args:
        link_reference_number (str): ABDM Link Reference Number.
        updated_data (dict): Data to update.

    Returns:
        bool
    """
    with session_scope() as session:
        row = (
            session.query(LinkSession)
            .filter(LinkSession.link_reference_number == link_reference_number)
            .one_or_none()
        )
        if row is None:
            return False

        merged = dict(row.data)
        merged.update(updated_data)
        row.data = merged

        return True


# -----------------------------------------------------------------------------
# Delete Link Session
# -----------------------------------------------------------------------------

def delete_link_session(link_reference_number):
    """
    Deletes a stored link session. Returns True if the session existed
    immediately before this call, False otherwise.

    Args:
        link_reference_number (str): ABDM Link Reference Number.

    Returns:
        bool
    """
    with session_scope() as session:
        deleted = (
            session.query(LinkSession)
            .filter(LinkSession.link_reference_number == link_reference_number)
            .delete()
        )
        return deleted > 0


# -----------------------------------------------------------------------------
# Check if Link Session Exists
# -----------------------------------------------------------------------------

def link_session_exists(link_reference_number):
    """
    Checks if a link session exists.

    Args:
        link_reference_number (str): ABDM Link Reference Number.

    Returns:
        bool
    """
    with session_scope() as session:
        return (
            session.query(LinkSession.id)
            .filter(LinkSession.link_reference_number == link_reference_number)
            .first()
            is not None
        )


# -----------------------------------------------------------------------------
# Get All Link Sessions (Debugging Only)
# -----------------------------------------------------------------------------

def get_all_link_sessions():
    """
    Returns all stored link sessions.

    Returns:
        dict
    """
    with session_scope() as session:
        rows = session.query(LinkSession).all()
        return {row.link_reference_number: row.data for row in rows}


# -----------------------------------------------------------------------------
# Clear All Link Sessions (Debugging Only)
# -----------------------------------------------------------------------------

def clear_all_link_sessions():
    """
    Clears all stored link sessions -- a real bulk DELETE now (P17); the
    file-backed version's own "append-only log has no true truncate"
    limitation doesn't apply to a real table. Debugging only; no caller
    in this codebase today.

    Returns:
        None
    """
    with session_scope() as session:
        session.query(LinkSession).delete()
