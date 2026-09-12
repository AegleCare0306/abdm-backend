"""
Repository for storing received Health Information (M3 Block 2's end
state: the decrypted FHIR bundle per care context, delivered via the
HIP's direct data push to our dataPushUrl), keyed by transactionId.

Deliberately separate from server/callbacks/repository/
health_information_repository.py (M2's HIP-role session store for the
data it PUSHES out) even though both roles run on the same server for
sandbox testing -- merging them risks one role's code misreading the
other's data. See this package's pending_health_information_request_repository.py
for the same reasoning applied to the pending-session side of this flow.

Current Implementation:
    - Postgres, via server/db.py + server/db_models.py:HiuHealthInformation
      (P17, 2026-09-07) -- moved off the prior file-backed
      storage/hiu_health_information.jsonl. See
      hiu_consent_repository.py's own banner for the full P16/P17 story
      (why Postgres, why now).
    - NOTE ON SIZE: this file was 14.9 MB across only 118 live keys
      (~127 KB average payload -- full FHIR bundles per transaction, not
      small metadata dicts like most other stores in this codebase).
      Postgres JSONB handles a payload this size with no special
      handling needed (TOAST storage is automatic).
    - Every function's name, signature, and return contract is
      byte-for-byte identical to the file-backed version -- no caller
      outside this file needed to change.
    - deepcopy() calls from the file-backed version are gone: a JSONB
      column deserializes to a fresh Python dict per query, so there is
      no shared/cached object for a caller's mutation to corrupt anymore.

Prior Implementation (superseded, see storage/hiu_health_information.jsonl
-- kept as an inert audit trail, not the live source of truth anymore):
    - File-backed, append-only JSON log, same pattern as
      hiu_consent_repository.py, for the same reasons: survives
      cross-process access and `--reload` restarts, and tolerates a
      couple of testers writing concurrently.
"""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from server.db import session_scope
from server.db_models import HiuHealthInformation


def save_hiu_health_information(transaction_id, data):
    """
    Stores received health information for one transaction, keyed by
    transactionId. `data` is expected to carry a "care_contexts" dict
    ({care_context_reference: {hi_status, description, bundle,
    received_at}}), plus whatever else the caller finds useful
    (consent_id, hip_id, page_number, page_count) -- this function
    doesn't inspect the shape, it just stores it. Upsert -- always
    overwrites any existing row for this transaction_id, same "no
    merge" contract the file-backed set_key() had (page-by-page merging,
    where it happens, is done by the CALLER before this is invoked -- see
    health_information_hiu_push_service.py).
    """
    with session_scope() as session:
        stmt = pg_insert(HiuHealthInformation).values(transaction_id=transaction_id, data=data)
        stmt = stmt.on_conflict_do_update(
            index_elements=[HiuHealthInformation.transaction_id],
            set_={"data": stmt.excluded.data, "updated_at": func.now()},
        )
        session.execute(stmt)


def get_hiu_health_information(transaction_id):
    """
    Retrieves stored health information for one transaction. Returns
    None if not found.
    """
    with session_scope() as session:
        row = (
            session.query(HiuHealthInformation)
            .filter(HiuHealthInformation.transaction_id == transaction_id)
            .one_or_none()
        )
        return row.data if row is not None else None


def delete_hiu_health_information(transaction_id):
    """
    Deletes stored health information for one transaction. Returns True
    if it existed immediately before this call, False otherwise.
    """
    with session_scope() as session:
        deleted = (
            session.query(HiuHealthInformation)
            .filter(HiuHealthInformation.transaction_id == transaction_id)
            .delete()
        )
        return deleted > 0


def get_all_hiu_health_information():
    """
    Debugging helper.
    """
    with session_scope() as session:
        rows = session.query(HiuHealthInformation).all()
        return {row.transaction_id: row.data for row in rows}
