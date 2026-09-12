"""
Repository for storing patient identity information resolved by
Discover, consumed by Link Init and Link Confirm, keyed by
abha_address.

Current Implementation:
    - Postgres, via server/db.py + server/db_models.py:PatientIdentity
      (P16, 2026-09-07) -- moved off the prior file-backed
      storage/patient_identities.jsonl (server/callbacks/utils/
      json_file_store.py). See hiu_consent_repository.py's own banner for
      the full P16 story (why Postgres, why now).
    - Every function's name, signature, and return contract is
      byte-for-byte identical to the file-backed version -- no caller
      outside this file needed to change.
    - deepcopy() calls from the file-backed version are gone: a JSONB
      column deserializes to a fresh Python dict per query, so there is
      no shared/cached object for a caller's mutation to corrupt anymore.

Prior Implementation (superseded, see storage/patient_identities.jsonl --
kept as an inert audit trail, not the live source of truth anymore):
    - File-backed, append-only JSON log -- CHANGED 2026-08-05, was a plain
      in-memory dict (T-80 on the To-Do Tracker). Same reason as every
      other repository converted this way: identity resolved by Discover
      in one server process (e.g. before a `--reload` restart) was
      invisible to a later process handling Link Init/Link Confirm, and
      get_patient_identity() returning None in that case was silently
      swallowed -- no on-init/on-confirm response and no error
      acknowledgment sent to ABDM, leaving the CM waiting on a callback
      that never arrives.
"""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from server.db import session_scope
from server.db_models import PatientIdentity


def save_patient_identity(
    abha_address,
    patient_data,
):
    """
    Stores patient identity information. Upsert -- always overwrites any
    existing row for this abha_address, same "no merge" contract the
    file-backed set_key() had.

    Args:
        abha_address (str)
        patient_data (dict)
    """
    with session_scope() as session:
        stmt = pg_insert(PatientIdentity).values(abha_address=abha_address, data=patient_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=[PatientIdentity.abha_address],
            set_={"data": stmt.excluded.data, "updated_at": func.now()},
        )
        session.execute(stmt)


def get_patient_identity(
    abha_address,
):
    """
    Retrieves patient identity information.

    Args:
        abha_address (str)

    Returns:
        dict | None
    """
    with session_scope() as session:
        row = (
            session.query(PatientIdentity)
            .filter(PatientIdentity.abha_address == abha_address)
            .one_or_none()
        )
        return row.data if row is not None else None
