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

Current Implementation:
    - File-backed, append-only JSON log under storage/hiu_consents.jsonl
      (via server/callbacks/utils/json_file_store.py) -- same pattern as
      consent_repository.py, for the same reasons: survives cross-process
      access and `--reload` restarts, and tolerates a couple of testers
      writing concurrently (see json_file_store.py's own docstring for
      why append-only is the chosen middle ground, not a full database).
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

_STORE_FILE = "hiu_consents.jsonl"


def save_hiu_consent(consent_id, consent_data):
    """
    Stores a fetched HIU-role consent artefact, keyed by consentId.
    """

    set_key(_STORE_FILE, consent_id, deepcopy(consent_data))


def get_hiu_consent(consent_id):
    """
    Retrieves a stored HIU-role consent artefact. Returns None if not
    found.
    """

    consent = get_key(_STORE_FILE, consent_id)

    if consent is None:
        return None

    return deepcopy(consent)


def delete_hiu_consent(consent_id):
    """
    Deletes a stored HIU-role consent artefact (appends a delete
    tombstone -- see json_file_store.py). Returns True if the consent
    existed immediately before this call, False otherwise.
    """

    return delete_key(_STORE_FILE, consent_id)


def get_all_hiu_consents():
    """
    Debugging helper.
    """

    return deepcopy(
        get_all(_STORE_FILE)
    )
