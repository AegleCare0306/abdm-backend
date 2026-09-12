"""
Repository for temporarily storing pending HIU-initiated Health
Information Request sessions (M3 Block 2: Health Information Request ->
on-request ack -> data push -> notify).

TWO-KEY LOOKUP: a pending health information request session is saved
under our own REQUEST-ID at initiate_health_information_request() time
(server/hiu_health_information.py), but the later data push (POST
/api/v3/hiu/health-information/push) arrives keyed by ABDM's own
transactionId, not our REQUEST-ID -- that real id only becomes known
once the on-request callback delivers it. Same pattern as
pending_consent_request_repository.py's link_consent_request_id() -- a
second, separate index TABLE (transactionId -> REQUEST-ID) layered on
top of the same underlying record, rather than duplicating the record
itself under two different keys. See that module's own docstring for the
full reasoning (kept identical here, just renamed).

This repository is scoped to the HIU role's own Health Information
Request flow only. It is intentionally separate from
health_information_repository.py (M2's HIP-role session store for the
data it PUSHES) and hiu_health_information_repository.py (the received
data store) -- do not merge these; both roles run on the same server for
sandbox testing, and mixing their storage risks one role's code
misreading the other's data.

Current Implementation:
    - Postgres, via server/db.py + server/db_models.py:
      PendingHealthInformationRequest (main table) +
      PendingHealthInformationRequestByTransactionId (index table) --
      P17, 2026-09-07. Moved off the prior file-backed
      storage/pending_health_information_requests.jsonl +
      storage/pending_health_information_requests_by_transaction_id.jsonl.
      Preserved as TWO separate tables, matching the two-file shape
      exactly. See hiu_consent_repository.py's own banner for the full
      P16/P17 story (why Postgres, why now).
    - link_transaction_id() writes BOTH tables in ONE transaction (single
      session_scope() block) -- the two tables commit together or neither
      does, so they can't drift out of sync the way two independent
      unguarded writes could.
    - get_unlinked_pending_health_information_requests()'s own "falsy"
      filter is preserved as a genuine three-way check (NULL, missing
      key, OR empty string), not simplified to `IS NULL` alone -- see
      that function's own docstring for why the distinction matters.
    - Every function's name, signature, and return contract is
      byte-for-byte identical to the file-backed version -- no caller
      outside this file needed to change.

Prior Implementation (superseded, see the two storage/*.jsonl files above
-- kept as an inert audit trail, not the live source of truth anymore):
    - File-backed (not in-memory), same reasoning as every other pending-*
      repository in this codebase -- the CLI/service processes are
      separate OS processes and both need to see the same pending
      session.
"""

from sqlalchemy import func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from server.db import session_scope
from server.db_models import PendingHealthInformationRequest, PendingHealthInformationRequestByTransactionId


def save_pending_health_information_request(request_id, data):
    """
    Saves a pending health information request session, keyed by the
    REQUEST-ID sent to ABDM with the originating outbound call
    (data-flow/v3/health-information/request). Upsert -- always
    overwrites any existing row for this request_id, same "no merge"
    contract the file-backed set_key() had.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            originating call.
        data (dict): Pending session information.

    Returns:
        None
    """
    with session_scope() as session:
        stmt = pg_insert(PendingHealthInformationRequest).values(request_id=request_id, data=data)
        stmt = stmt.on_conflict_do_update(
            index_elements=[PendingHealthInformationRequest.request_id],
            set_={"data": stmt.excluded.data, "updated_at": func.now()},
        )
        session.execute(stmt)


def get_pending_health_information_request(request_id):
    """
    Retrieves a pending health information request session by our own
    REQUEST-ID.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            originating call.

    Returns:
        dict | None
    """
    with session_scope() as session:
        row = (
            session.query(PendingHealthInformationRequest)
            .filter(PendingHealthInformationRequest.request_id == request_id)
            .one_or_none()
        )
        return row.data if row is not None else None


def link_transaction_id(request_id, transaction_id):
    """
    Called once the on-request callback delivers ABDM's real
    transactionId for a pending session -- records
    transaction_id -> request_id in the separate index table, and merges
    transaction_id into the stored session itself (so a lookup by either
    key returns a record carrying it). Both writes happen in ONE
    transaction (see this module's own banner).

    Args:
        request_id (str): The REQUEST-ID this session was originally
            saved under.
        transaction_id (str): ABDM's real transactionId, delivered via
            the on-request callback.

    Returns:
        dict | None: The updated session data, or None if request_id has
            no pending session to update.
    """
    with session_scope() as session:
        row = (
            session.query(PendingHealthInformationRequest)
            .filter(PendingHealthInformationRequest.request_id == request_id)
            .one_or_none()
        )
        if row is None:
            return None

        updated = dict(row.data)
        updated["transaction_id"] = transaction_id
        row.data = updated

        index_stmt = pg_insert(PendingHealthInformationRequestByTransactionId).values(
            transaction_id=transaction_id, request_id=request_id
        )
        index_stmt = index_stmt.on_conflict_do_update(
            index_elements=[PendingHealthInformationRequestByTransactionId.transaction_id],
            set_={"request_id": index_stmt.excluded.request_id},
        )
        session.execute(index_stmt)

        return updated


def get_request_id_for_transaction_id(transaction_id):
    """
    Looks up which REQUEST-ID a transactionId is currently linked to in
    the index table, without resolving the full session record. Used by
    the on-request callback handler (tracker case M3-2) to detect a
    transactionId collision BEFORE calling link_transaction_id() -- see
    that function's own docstring for why an unconditional relink is
    dangerous: two overlapping Health Information Requests in flight at
    once (two different REQUEST-IDs, each with its own pending session
    and its own key_material) could otherwise have their sessions crossed
    if a second on-request callback claims a transactionId already linked
    to a different REQUEST-ID's session -- silently overwriting the index
    entry so the later data push resolves to the WRONG session's
    key_material, and a genuinely correct push gets decrypted with the
    wrong key and reported as failed.

    Args:
        transaction_id (str): ABDM's real transactionId.

    Returns:
        str | None: The REQUEST-ID currently linked to this
            transactionId, or None if nothing is linked yet.
    """
    with session_scope() as session:
        index_row = (
            session.query(PendingHealthInformationRequestByTransactionId)
            .filter(PendingHealthInformationRequestByTransactionId.transaction_id == transaction_id)
            .one_or_none()
        )
        return index_row.request_id if index_row is not None else None


def get_pending_health_information_request_by_transaction_id(transaction_id):
    """
    Retrieves a pending health information request session by ABDM's
    real transactionId -- only resolvable after link_transaction_id() has
    been called for it (i.e. after the on-request callback has arrived).

    Args:
        transaction_id (str): ABDM's real transactionId.

    Returns:
        dict | None
    """
    with session_scope() as session:
        index_row = (
            session.query(PendingHealthInformationRequestByTransactionId)
            .filter(PendingHealthInformationRequestByTransactionId.transaction_id == transaction_id)
            .one_or_none()
        )
        if index_row is None:
            return None

        row = (
            session.query(PendingHealthInformationRequest)
            .filter(PendingHealthInformationRequest.request_id == index_row.request_id)
            .one_or_none()
        )
        return row.data if row is not None else None


def get_unlinked_pending_health_information_requests():
    """
    Returns {request_id: session} for every pending session that has NOT
    yet been linked to a transactionId (session["transaction_id"] is
    missing, NULL, or an empty string) -- i.e. every Health Information
    Request that's still waiting on its on-request ack.

    WHY THIS EXISTS (2026-09-03, confirmed live): the data push can
    arrive BEFORE -- or, confirmed live, sometimes without ever receiving
    -- the on-request callback that normally supplies the transactionId
    correlation (see link_transaction_id()'s own docstring for the normal
    path). A push with no linked session used to just be dropped, silently
    discarding real, successfully-decryptable patient data. This is the
    fallback lookup health_information_hiu_push_service.py's own
    push handler uses as a last resort, once a short retry on the normal
    by-transaction-id lookup has already failed: if exactly ONE unlinked
    session exists, it's used as the best available match.

    THREE-WAY FALSY CHECK, preserved exactly from the file-backed version
    (P17, 2026-09-07): the original Python code was `not session.get(
    "transaction_id")`, which treats a missing key, a JSON `null`, AND an
    empty string `""` all as "not linked yet." A Postgres query that only
    checked `IS NULL` would silently stop matching a session whose
    transaction_id field exists but is an empty string -- a real, if
    narrow, behavior change nothing currently in this codebase would
    notice until it happened live. `data->>'transaction_id'` (SQLAlchemy's
    `.astext`) returns NULL for both "key missing" and "value is JSON
    null" alike, so `IS NULL OR = ''` covers all three cases correctly.

    Returns:
        dict[str, dict]: request_id -> session, for every session still
            missing a transaction_id. Empty dict if none.
    """
    with session_scope() as session:
        transaction_id_text = PendingHealthInformationRequest.data["transaction_id"].astext
        rows = (
            session.query(PendingHealthInformationRequest)
            .filter(or_(transaction_id_text.is_(None), transaction_id_text == ""))
            .all()
        )
        return {row.request_id: row.data for row in rows}


def delete_pending_health_information_request(request_id):
    """
    Deletes a pending health information request session by our own
    REQUEST-ID. Does not clean up any transaction_id index entry
    pointing at it -- a stale index entry simply resolves to a
    now-missing record afterward, handled the same as "not found" by
    every caller here, consistent with how the rest of this codebase
    leaves tombstoned/orphaned keys behind rather than doing cross-file
    cleanup.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            originating call.

    Returns:
        bool
    """
    with session_scope() as session:
        deleted = (
            session.query(PendingHealthInformationRequest)
            .filter(PendingHealthInformationRequest.request_id == request_id)
            .delete()
        )
        return deleted > 0
