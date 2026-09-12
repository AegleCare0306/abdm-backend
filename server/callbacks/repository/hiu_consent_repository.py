"""
Repository for storing fully-fetched Consent artefacts obtained by us
acting as an HIU (M3 Block 1's end state: consentDetail + signature,
delivered via the on-fetch callback), keyed by consentId.

Deliberately separate from server/callbacks/repository/consent_repository.py
(M2's store for consents WE, as an HIP, received notification of) even
though both roles run on the same server for sandbox testing -- merging
them risks one role's code misreading the other's data. See this
package's pending_consent_request_repository.py for the same reasoning
applied to the pending-session side of this flow.

THE SECURITY PROPERTY THIS MODULE ENFORCES (P16, 2026-09-07 -- read before
touching anything here): get_hiu_consent(consent_id) returns a row ONLY IF
save_hiu_consent() was called for that exact id -- which only ever happens
from server/callbacks/services/consent_hiu_on_fetch_service.py, in
response to a genuine on-fetch callback for a consent THIS registration's
own hiu_consent.py flow itself requested. A consent raised through a
different app/registration is structurally absent here, full stop,
regardless of what ABDM itself thinks its status is. That is not a side
effect of file storage -- it is the whole point of this cache being keyed
by "did we ourselves put this here." Moving to Postgres below preserves
this exactly: nothing here makes a foreign/ABDM-visible consent become
readable just because a database can technically hold more than this
process wrote.

Current Implementation:
    - Postgres, via server/db.py + server/db_models.py:HiuConsent (P16,
      2026-09-07) -- moved off the prior file-backed
      storage/hiu_consents.jsonl (server/callbacks/utils/json_file_store.py)
      specifically so this state isn't tied to one process's local files
      (see the P16 task prompt for the real question that prompted this:
      a record linked through a different registration couldn't be
      retrieved here, because this cache only ever held what THIS
      registration itself fetched -- moving to Postgres does not change
      that gate, it only stops the gate from living in a fragile
      per-process file. See this module's own banner above).
    - Every function's name, signature, and return contract is
      byte-for-byte identical to the file-backed version -- no caller
      outside this file needed to change.
    - deepcopy() calls from the file-backed version are gone: a JSONB
      column deserializes to a fresh Python dict per query, so there is
      no shared/cached object for a caller's mutation to corrupt anymore.

Prior Implementation (superseded, see storage/hiu_consents.jsonl -- kept
as an inert audit trail, not the live source of truth anymore):
    - File-backed, append-only JSON log, same pattern as
      consent_repository.py -- see that module's own history for the
      full reasoning trail (cross-process/restart durability, then
      append-only for light concurrency).
"""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from server.db import session_scope
from server.db_models import HiuConsent


def save_hiu_consent(consent_id, consent_data):
    """
    Stores a fetched HIU-role consent artefact, keyed by consentId.
    Upsert -- always overwrites any existing row for this consent_id,
    same "no merge" contract the file-backed set_key() had.
    """
    with session_scope() as session:
        stmt = pg_insert(HiuConsent).values(consent_id=consent_id, data=consent_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=[HiuConsent.consent_id],
            set_={"data": stmt.excluded.data, "updated_at": func.now()},
        )
        session.execute(stmt)


def get_hiu_consent(consent_id):
    """
    Retrieves a stored HIU-role consent artefact. Returns None if not
    found.
    """
    with session_scope() as session:
        row = session.query(HiuConsent).filter(HiuConsent.consent_id == consent_id).one_or_none()
        return row.data if row is not None else None


def delete_hiu_consent(consent_id):
    """
    Deletes a stored HIU-role consent artefact. Returns True if the
    consent existed immediately before this call, False otherwise.
    """
    with session_scope() as session:
        deleted = session.query(HiuConsent).filter(HiuConsent.consent_id == consent_id).delete()
        return deleted > 0


def get_all_hiu_consents():
    """
    Debugging helper.
    """
    with session_scope() as session:
        rows = session.query(HiuConsent).all()
        return {row.consent_id: row.data for row in rows}
