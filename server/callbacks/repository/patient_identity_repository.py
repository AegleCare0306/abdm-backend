"""
Repository for storing patient identity information resolved by
Discover, consumed by Link Init and Link Confirm, keyed by
abha_address.

Current Implementation:
    - File-backed, append-only JSON log under storage/patient_identities.jsonl
      (via server/callbacks/utils/json_file_store.py) -- CHANGED
      2026-08-05, was a plain in-memory dict (T-80 on the To-Do Tracker).
      Same reason as every other repository converted this way: identity
      resolved by Discover in one server process (e.g. before a
      `--reload` restart) was invisible to a later process handling
      Link Init/Link Confirm, and get_patient_identity() returning None
      in that case was silently swallowed -- no on-init/on-confirm
      response and no error acknowledgment sent to ABDM, leaving the CM
      waiting on a callback that never arrives. Concurrency-wise, same
      append-only middle ground as the other stores -- see
      json_file_store.py's own docstring for why this is NOT a full
      database, just safe enough for a couple of testers working at
      once.
    - Contains real patient/ABHA data -- gitignored, same as the other
      file-backed stores.

Future Implementation:
    - Redis
    - PostgreSQL
    - MongoDB
"""

from copy import deepcopy

from server.callbacks.utils.json_file_store import set_key, get_key

_STORE_FILE = "patient_identities.jsonl"


def save_patient_identity(
    abha_address,
    patient_data,
):
    """
    Stores patient identity information.

    Args:
        abha_address (str)
        patient_data (dict)
    """

    set_key(_STORE_FILE, abha_address, deepcopy(patient_data))


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

    patient = get_key(_STORE_FILE, abha_address)

    if patient is None:
        return None

    return deepcopy(patient)
