"""
Repository for temporarily storing pending HIU-initiated Consent Request
sessions (M3 Block 1: Consent Init Request -> on-init -> notify -> Fetch
-> on-fetch).

TWO-KEY LOOKUP: a pending consent request session is saved under our own
REQUEST-ID at initiate_consent_request() time (server/hiu_consent.py),
but the later notify callback (POST /api/v3/hiu/consent/request/notify)
arrives keyed by ABDM's own consentRequestId, not our REQUEST-ID -- that
real id only becomes known once the on-init callback delivers it. To
correlate the notify callback back to the original session without
changing json_file_store.py's single-key API, this module keeps a
second, separate index file (consentRequestId -> REQUEST-ID) and layers
a by-consent-request-id lookup on top of the same underlying record,
rather than duplicating the record itself under two different keys.

File-backed (not in-memory), same reasoning as
link_token_repository.py -- the CLI/service processes are separate OS
processes and both need to see the same pending session, and this
codebase already learned the hard way (2026-08-04) that an in-memory
dict doesn't survive `--reload` restarts or cross-process reads.

This repository is scoped to the HIU role's own Consent Init Request
flow only. It is intentionally separate from consent_repository.py (M2's
HIP-received consent artifact store) and hiu_consent_repository.py (the
fetched consent artefact store, below) -- do not merge these; both roles
run on the same server for sandbox testing, and mixing their storage
risks one role's code misreading the other's data.

Future Implementation:
    - Redis
    - PostgreSQL
    - MongoDB
"""

from server.callbacks.utils.json_file_store import set_key, get_key, delete_key

_STORE_FILE = "pending_consent_requests.jsonl"
_INDEX_FILE = "pending_consent_requests_by_consent_request_id.jsonl"


def save_pending_consent_request(request_id, data):
    """
    Saves a pending consent request session, keyed by the REQUEST-ID sent
    to ABDM with the originating outbound call (consent/v3/request/init
    or consent/v3/fetch).

    Args:
        request_id (str): REQUEST-ID header value sent with the
            originating call.
        data (dict): Pending session information.

    Returns:
        None
    """

    set_key(_STORE_FILE, request_id, data)


def get_pending_consent_request(request_id):
    """
    Retrieves a pending consent request session by our own REQUEST-ID.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            originating call.

    Returns:
        dict | None
    """

    return get_key(_STORE_FILE, request_id)


def link_consent_request_id(request_id, consent_request_id):
    """
    Called once the on-init callback delivers ABDM's real
    consentRequest.id for a pending session -- records
    consent_request_id -> request_id in the separate index file, and
    merges consent_request_id into the stored session itself (so a
    lookup by either key returns a record carrying it).

    Args:
        request_id (str): The REQUEST-ID this session was originally
            saved under.
        consent_request_id (str): ABDM's real consentRequest.id,
            delivered via the on-init callback.

    Returns:
        dict | None: The updated session data, or None if request_id has
            no pending session to update.
    """

    session = get_key(_STORE_FILE, request_id)
    if session is None:
        return None

    updated = dict(session)
    updated["consent_request_id"] = consent_request_id

    set_key(_STORE_FILE, request_id, updated)
    set_key(_INDEX_FILE, consent_request_id, request_id)

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

    request_id = get_key(_INDEX_FILE, consent_request_id)
    if request_id is None:
        return None

    return get_key(_STORE_FILE, request_id)


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

    return delete_key(_STORE_FILE, request_id)
