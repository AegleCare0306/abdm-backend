"""
Repository for storing granted Consent artifacts, keyed by consentId.

Current Implementation:
    - File-backed, append-only JSON log under storage/consents.jsonl
      (via server/callbacks/utils/json_file_store.py) -- CHANGED
      2026-08-05, was a plain in-memory dict. Two real reasons:
      (1) same cross-process/cross-restart gap already fixed for the
      other repositories in this codebase -- a consent granted by one
      server process (e.g. before a `--reload` restart) was invisible
      to a later process, even though ABDM still considers that
      consentId validly granted and will reference it again in a later
      Health Information Request. (2) discussed 2026-08-05: multiple
      people/requests genuinely writing concurrently needs more than a
      plain dict or a read-modify-write file -- see
      json_file_store.py's own docstring for why append-only is the
      chosen middle ground (not a full database, but safe enough for a
      couple of testers working at once).
    - Still not database-grade concurrency -- see json_file_store.py.
    - Contains real patient/consent data -- gitignored, same as the
      other file-backed stores.

Future Implementation:
    - Redis
    - PostgreSQL
    - MongoDB
"""

from copy import deepcopy

from server.callbacks.utils.json_file_store import set_key, get_key, delete_key, get_all

_STORE_FILE = "consents.jsonl"


def save_consent(
    consent_id,
    consent_data,
):
    """
    Stores a granted Consent artifact, keyed by consentId.
    """

    set_key(_STORE_FILE, consent_id, deepcopy(consent_data))


def get_consent(
    consent_id,
):
    """
    Retrieves a stored Consent artifact. Returns None if not found
    (e.g. the consent was denied/revoked and never stored, or the
    consentId is unrecognized).
    """

    consent = get_key(_STORE_FILE, consent_id)

    if consent is None:
        return None

    return deepcopy(consent)


def delete_consent(
    consent_id,
):
    """
    Deletes a stored Consent artifact (appends a delete tombstone --
    see json_file_store.py). Returns True if the consent existed
    immediately before this call, False otherwise.
    """

    return delete_key(_STORE_FILE, consent_id)


def get_all_consents():
    """
    Debugging helper.
    """

    return deepcopy(
        get_all(_STORE_FILE)
    )
