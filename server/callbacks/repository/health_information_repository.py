"""
Repository for temporarily storing Health Information Request sessions
(M2/HIP-role: the data THIS server pushes out to an HIU, as opposed to
hiu_health_information_repository.py, the HIU-role store for data
RECEIVED -- deliberately separate tables, same "don't merge, one role's
code could misread the other's data" rule as every other pair of stores
in this codebase).

Current Implementation (P17, 2026-09-07):
    - Postgres, via server/db.py + server/db_models.py:
      HealthInformationSession.

    UNLIKE EVERY OTHER REPOSITORY MODULE MOVED IN P16/P17, this one
    replaces an IN-MEMORY dict, not a file -- a genuine behavior change,
    not a pure storage-backend swap: state now survives a process
    restart and is visible across OS processes, neither of which was
    true before. Nothing was backfilled for this table -- the in-memory
    dict this replaces is always empty at the moment any migration runs,
    so there was nothing to carry over.

    update_health_information_session() does a PARTIAL MERGE
    (`dict.update()` in the old in-memory version), NOT an overwrite --
    preserved here via Postgres's JSONB `||` concat operator
    (`data || updated_data`), which matches Python's shallow-merge
    semantics exactly: keys in `updated_data` win on conflict, every
    other existing key is left untouched. Implemented as a single Core
    UPDATE statement (not a load-then-save round trip) so the merge
    happens atomically in the database.

    Every function's name, signature, and return contract is
    byte-for-byte identical to the prior in-memory version -- no caller
    outside this file needed to change.

Prior Implementation (superseded):
    - Plain module-level dict (`_health_information_sessions = {}`) --
      lost on every restart, invisible across OS processes. Never
      converted to file-backed storage the way every other repository in
      this codebase was (T-80 and friends) -- this is the one exception
      P17 finally closes.

Future Implementation:
    - (none -- this is now on the same footing as every other repository
      module in this codebase)
"""

from sqlalchemy import func, type_coerce
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from server.db import session_scope
from server.db_models import HealthInformationSession


def save_health_information_session(
    transaction_id,
    session_data,
):
    """
    Stores a Health Information Request session. Upsert -- always
    overwrites any existing row for this transaction_id, same "always
    overwrites, no merge" contract the old in-memory
    `_health_information_sessions[transaction_id] = ...` assignment had.
    """
    with session_scope() as session:
        stmt = pg_insert(HealthInformationSession).values(transaction_id=transaction_id, data=session_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=[HealthInformationSession.transaction_id],
            set_={"data": stmt.excluded.data, "updated_at": func.now()},
        )
        session.execute(stmt)


def get_health_information_session(
    transaction_id,
):
    """
    Retrieves a stored Health Information Request session. Returns None
    if not found.
    """
    with session_scope() as session:
        row = (
            session.query(HealthInformationSession)
            .filter(HealthInformationSession.transaction_id == transaction_id)
            .one_or_none()
        )
        return row.data if row is not None else None


def update_health_information_session(
    transaction_id,
    updated_data,
):
    """
    Updates an existing session with a PARTIAL MERGE (matching the old
    in-memory version's `dict.update()` exactly, via Postgres's JSONB
    `||` concat operator -- `updated_data`'s keys win on conflict, every
    other existing key is left untouched). Returns False without writing
    anything if the session doesn't currently exist -- same contract as
    the old in-memory version's own `if transaction_id not in ...` guard.
    """
    with session_scope() as session:
        stmt = (
            sa_update(HealthInformationSession)
            .where(HealthInformationSession.transaction_id == transaction_id)
            .values(
                data=HealthInformationSession.data.op("||")(type_coerce(updated_data, JSONB)),
                updated_at=func.now(),
            )
        )
        result = session.execute(stmt)
        return result.rowcount > 0


def delete_health_information_session(
    transaction_id,
):
    """
    Deletes a stored session. Returns True if it existed immediately
    before this call, False otherwise.
    """
    with session_scope() as session:
        deleted = (
            session.query(HealthInformationSession)
            .filter(HealthInformationSession.transaction_id == transaction_id)
            .delete()
        )
        return deleted > 0


def get_all_health_information_sessions():
    """
    Debugging helper.
    """
    with session_scope() as session:
        rows = session.query(HealthInformationSession).all()
        return {row.transaction_id: row.data for row in rows}
