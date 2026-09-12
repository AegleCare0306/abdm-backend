"""
Repository for storing granted Consent artifacts, keyed by consentId.

Current Implementation:
    - Postgres, via server/db.py + server/db_models.py:Consent (P16,
      2026-09-07) -- moved off the prior file-backed storage/consents.jsonl
      (server/callbacks/utils/json_file_store.py). See
      hiu_consent_repository.py's own banner for the full P16 story (why
      Postgres, why now) -- this module is the M2/HIP-role sibling of
      that one, kept as a genuinely separate table on purpose (see that
      module's own docstring on why merging the two risks one role's code
      misreading the other's data).
    - Every function's name, signature, and return contract is
      byte-for-byte identical to the file-backed version -- no caller
      outside this file needed to change.
    - deepcopy() calls from the file-backed version are gone: a JSONB
      column deserializes to a fresh Python dict per query, so there is
      no shared/cached object for a caller's mutation to corrupt anymore.

Prior Implementation (superseded, see storage/consents.jsonl -- kept as an
inert audit trail, not the live source of truth anymore):
    - File-backed, append-only JSON log -- CHANGED 2026-08-05, was a plain
      in-memory dict, for two reasons: (1) cross-process/cross-restart
      durability -- a consent granted by one server process (e.g. before
      a `--reload` restart) was invisible to a later process, even though
      ABDM still considers that consentId validly granted. (2) light
      concurrent-write safety for a couple of testers working at once --
      see json_file_store.py's own docstring for why append-only was the
      chosen middle ground, not a full database, until now.
"""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from server.db import session_scope
from server.db_models import Consent


def save_consent(
    consent_id,
    consent_data,
):
    """
    Stores a granted Consent artifact, keyed by consentId. Upsert --
    always overwrites any existing row for this consent_id, same "no
    merge" contract the file-backed set_key() had.
    """
    with session_scope() as session:
        stmt = pg_insert(Consent).values(consent_id=consent_id, data=consent_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Consent.consent_id],
            set_={"data": stmt.excluded.data, "updated_at": func.now()},
        )
        session.execute(stmt)


def get_consent(
    consent_id,
):
    """
    Retrieves a stored Consent artifact. Returns None if not found
    (e.g. the consent was denied/revoked and never stored, or the
    consentId is unrecognized).
    """
    with session_scope() as session:
        row = session.query(Consent).filter(Consent.consent_id == consent_id).one_or_none()
        return row.data if row is not None else None


def delete_consent(
    consent_id,
):
    """
    Deletes a stored Consent artifact. Returns True if the consent
    existed immediately before this call, False otherwise.
    """
    with session_scope() as session:
        deleted = session.query(Consent).filter(Consent.consent_id == consent_id).delete()
        return deleted > 0


def get_all_consents():
    """
    Debugging helper.
    """
    with session_scope() as session:
        rows = session.query(Consent).all()
        return {row.consent_id: row.data for row in rows}
