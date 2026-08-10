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
    - File-backed, append-only JSON log under
      storage/hiu_health_information.jsonl (via
      server/callbacks/utils/json_file_store.py) -- same pattern as
      hiu_consent_repository.py, for the same reasons: survives
      cross-process access and `--reload` restarts, and tolerates a
      couple of testers writing concurrently (see json_file_store.py's
      own docstring for why append-only is the chosen middle ground, not
      a full database).
    - Still not database-grade concurrency -- see json_file_store.py.
    - Contains real patient/health data -- gitignored, same as the other
      file-backed stores.

Future Implementation:
    - Redis
    - PostgreSQL
    - MongoDB
"""

from copy import deepcopy

from server.callbacks.utils.json_file_store import set_key, get_key, delete_key, get_all

_STORE_FILE = "hiu_health_information.jsonl"


def save_hiu_health_information(transaction_id, data):
    """
    Stores received health information for one transaction, keyed by
    transactionId. `data` is expected to carry a "care_contexts" dict
    ({care_context_reference: {hi_status, description, bundle,
    received_at}}), plus whatever else the caller finds useful
    (consent_id, hip_id, page_number, page_count) -- this function
    doesn't inspect the shape, it just stores it.
    """

    set_key(_STORE_FILE, transaction_id, deepcopy(data))


def get_hiu_health_information(transaction_id):
    """
    Retrieves stored health information for one transaction. Returns
    None if not found.
    """

    data = get_key(_STORE_FILE, transaction_id)

    if data is None:
        return None

    return deepcopy(data)


def delete_hiu_health_information(transaction_id):
    """
    Deletes stored health information for one transaction (appends a
    delete tombstone -- see json_file_store.py). Returns True if it
    existed immediately before this call, False otherwise.
    """

    return delete_key(_STORE_FILE, transaction_id)


def get_all_hiu_health_information():
    """
    Debugging helper.
    """

    return deepcopy(
        get_all(_STORE_FILE)
    )
