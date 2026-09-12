"""
Repository for temporarily storing pending HIU-initiated Consent Request
sessions (M3 Block 1: Consent Init Request -> on-init -> notify -> Fetch
-> on-fetch).

TWO-KEY LOOKUP: a pending consent request session is saved under our own
REQUEST-ID at initiate_consent_request() time (server/hiu_consent.py),
but the later notify callback (POST /api/v3/hiu/consent/request/notify)
arrives keyed by ABDM's own consentRequestId, not our REQUEST-ID -- that
real id only becomes known once the on-init callback delivers it. To
correlate the notify callback back to the original session, this module
keeps a second, separate index TABLE (consentRequestId -> REQUEST-ID) and
layers a by-consent-request-id lookup on top of the same underlying
record, rather than duplicating the record itself under two different
keys.

This repository is scoped to the HIU role's own Consent Init Request
flow only. It is intentionally separate from consent_repository.py (M2's
HIP-received consent artifact store) and hiu_consent_repository.py (the
fetched consent artefact store) -- do not merge these; both roles run on
the same server for sandbox testing, and mixing their storage risks one
role's code misreading the other's data.

Current Implementation:
    - Postgres, via server/db.py + server/db_models.py:
      PendingConsentRequest (main table) +
      PendingConsentRequestByConsentRequestId (index table) -- P17,
      2026-09-07. Moved off the prior file-backed
      storage/pending_consent_requests.jsonl +
      storage/pending_consent_requests_by_consent_request_id.jsonl.
      Preserved as TWO separate tables, matching the two-file shape
      exactly -- not collapsed into one table with a second unique
      column, per P17's own scope (that's a reasonable future cleanup,
      not this pass). See hiu_consent_repository.py's own banner for the
      full P16/P17 story (why Postgres, why now).
    - link_consent_request_id() writes BOTH tables in ONE transaction
      (single session_scope() block) -- the two tables commit together or
      neither does, so they can't drift out of sync the way two
      independent unguarded writes could.
    - Every function's name, signature, and return contract is
      byte-for-byte identical to the file-backed version -- no caller
      outside this file needed to change.

Prior Implementation (superseded, see the two storage/*.jsonl files above
-- kept as an inert audit trail, not the live source of truth anymore):
    - File-backed (not in-memory), same reasoning as link_token_repository.py
      -- the CLI/service processes are separate OS processes and both need
      to see the same pending session.
"""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from server.db import session_scope
from server.db_models import PendingConsentRequest, PendingConsentRequestByConsentRequestId


def save_pending_consent_request(request_id, data):
    """
    Saves a pending consent request session, keyed by the REQUEST-ID sent
    to ABDM with the originating outbound call (consent/v3/request/init
    or consent/v3/fetch). Upsert -- always overwrites any existing row
    for this request_id, same "no merge" contract the file-backed
    set_key() had.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            originating call.
        data (dict): Pending session information.

    Returns:
        None
    """
    with session_scope() as session:
        stmt = pg_insert(PendingConsentRequest).values(request_id=request_id, data=data)
        stmt = stmt.on_conflict_do_update(
            index_elements=[PendingConsentRequest.request_id],
            set_={"data": stmt.excluded.data, "updated_at": func.now()},
        )
        session.execute(stmt)


def get_pending_consent_request(request_id):
    """
    Retrieves a pending consent request session by our own REQUEST-ID.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            originating call.

    Returns:
        dict | None
    """
    with session_scope() as session:
        row = (
            session.query(PendingConsentRequest)
            .filter(PendingConsentRequest.request_id == request_id)
            .one_or_none()
        )
        return row.data if row is not None else None


def link_consent_request_id(request_id, consent_request_id):
    """
    Called once the on-init callback delivers ABDM's real
    consentRequest.id for a pending session -- records
    consent_request_id -> request_id in the separate index table, and
    merges consent_request_id into the stored session itself (so a
    lookup by either key returns a record carrying it). Both writes
    happen in ONE transaction (see this module's own banner).

    Args:
        request_id (str): The REQUEST-ID this session was originally
            saved under.
        consent_request_id (str): ABDM's real consentRequest.id,
            delivered via the on-init callback.

    Returns:
        dict | None: The updated session data, or None if request_id has
            no pending session to update.
    """
    with session_scope() as session:
        row = (
            session.query(PendingConsentRequest)
            .filter(PendingConsentRequest.request_id == request_id)
            .one_or_none()
        )
        if row is None:
            return None

        updated = dict(row.data)
        updated["consent_request_id"] = consent_request_id
        row.data = updated

        index_stmt = pg_insert(PendingConsentRequestByConsentRequestId).values(
            consent_request_id=consent_request_id, request_id=request_id
        )
        index_stmt = index_stmt.on_conflict_do_update(
            index_elements=[PendingConsentRequestByConsentRequestId.consent_request_id],
            set_={"request_id": index_stmt.excluded.request_id},
        )
        session.execute(index_stmt)

        return updated


def get_pending_consent_request_by_consent_request_id(consent_request_id):
    """
    Retrieves a pending consent request session by ABDM's real
    consentRequestId -- only resolvable after link_consent_request_id()
    has been called for it (i.e. after the on-init callback has arrived).

    Args:
        consent_request_id (str): ABDM's real consentRequest.id.

    Returns:
        dict | None
    """
    with session_scope() as session:
        index_row = (
            session.query(PendingConsentRequestByConsentRequestId)
            .filter(PendingConsentRequestByConsentRequestId.consent_request_id == consent_request_id)
            .one_or_none()
        )
        if index_row is None:
            return None

        row = (
            session.query(PendingConsentRequest)
            .filter(PendingConsentRequest.request_id == index_row.request_id)
            .one_or_none()
        )
        return row.data if row is not None else None


def delete_pending_consent_request(request_id):
    """
    Deletes a pending consent request session by our own REQUEST-ID. Does
    not clean up any consent_request_id index entry pointing at it -- a
    stale index entry simply resolves to a now-missing record afterward,
    handled the same as "not found" by every caller here, consistent
    with how the rest of this codebase leaves tombstoned/orphaned keys
    behind rather than doing cross-file cleanup.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            originating call.

    Returns:
        bool
    """
    with session_scope() as session:
        deleted = (
            session.query(PendingConsentRequest)
            .filter(PendingConsentRequest.request_id == request_id)
            .delete()
        )
        return deleted > 0
