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
second, separate index file (transactionId -> REQUEST-ID) layered on top
of the same underlying record, rather than duplicating the record itself
under two different keys. See that module's own docstring for the full
reasoning (kept identical here, just renamed).

File-backed (not in-memory), same reasoning as every other pending-*
repository in this codebase -- the CLI/service processes are separate OS
processes and both need to see the same pending session.

This repository is scoped to the HIU role's own Health Information
Request flow only. It is intentionally separate from
health_information_repository.py (M2's HIP-role session store for the
data it PUSHES) and hiu_health_information_repository.py (the received
data store, below) -- do not merge these; both roles run on the same
server for sandbox testing, and mixing their storage risks one role's
code misreading the other's data.

Future Implementation:
    - Redis
    - PostgreSQL
    - MongoDB
"""

from server.callbacks.utils.json_file_store import set_key, get_key, delete_key

_STORE_FILE = "pending_health_information_requests.jsonl"
_INDEX_FILE = "pending_health_information_requests_by_transaction_id.jsonl"


def save_pending_health_information_request(request_id, data):
    """
    Saves a pending health information request session, keyed by the
    REQUEST-ID sent to ABDM with the originating outbound call
    (data-flow/v3/health-information/request).

    Args:
        request_id (str): REQUEST-ID header value sent with the
            originating call.
        data (dict): Pending session information.

    Returns:
        None
    """

    set_key(_STORE_FILE, request_id, data)


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

    return get_key(_STORE_FILE, request_id)


def link_transaction_id(request_id, transaction_id):
    """
    Called once the on-request callback delivers ABDM's real
    transactionId for a pending session -- records
    transaction_id -> request_id in the separate index file, and merges
    transaction_id into the stored session itself (so a lookup by either
    key returns a record carrying it).

    Args:
        request_id (str): The REQUEST-ID this session was originally
            saved under.
        transaction_id (str): ABDM's real transactionId, delivered via
            the on-request callback.

    Returns:
        dict | None: The updated session data, or None if request_id has
            no pending session to update.
    """

    session = get_key(_STORE_FILE, request_id)
    if session is None:
        return None

    updated = dict(session)
    updated["transaction_id"] = transaction_id

    set_key(_STORE_FILE, request_id, updated)
    set_key(_INDEX_FILE, transaction_id, request_id)

    return updated


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

    request_id = get_key(_INDEX_FILE, transaction_id)
    if request_id is None:
        return None

    return get_key(_STORE_FILE, request_id)


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

    return delete_key(_STORE_FILE, request_id)
