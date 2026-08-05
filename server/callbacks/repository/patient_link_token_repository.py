"""
Repository for persisting a patient's confirmed HIP-Initiated Linking
link token, keyed by ABHA address, so it can be reused across multiple
care-context operations (Linking Care Context, Notify Care Context
Update) instead of calling ABDM's generate-token API again for a patient
who already has one.

This is deliberately separate from link_token_repository.py, which
stores a PENDING session keyed by REQUEST-ID between the outbound
generate-token call and its on-generate-token callback, and is deleted
the moment that round-trip completes. This repository stores the
CONFIRMED result of that round-trip -- the real link token string --
keyed by the patient it belongs to, for indefinite reuse afterward.

UNCONFIRMED (flagged, not guessed): there is no confirmed information
anywhere -- the M2 doc or the Postman collection -- about a link token's
expiry/TTL, or how many times it can be reused before ABDM requires a
new one. The M2 doc does document `400 ABDM-1092 "Duplicate link token
request"` as a real generate-token failure mode, which confirms ABDM
does NOT want repeated generate-token calls for a patient who already
has a valid/pending token -- but that's the only signal available. No
expiry/TTL enforcement is implemented here as a result: a saved token is
reused indefinitely until ABDM's real behavior is confirmed otherwise.
`received_at` is stored for future reference in case that confirmation
ever arrives. Flagged on the Notion "Needs ABDM Spec Confirmation"
tracker.

Current Implementation:
    - File-backed JSON storage under storage/patient_link_tokens.json
      (via server/callbacks/utils/json_file_store.py), NOT a plain
      in-memory dict. CHANGED 2026-08-04 for the same reason as
      link_token_repository.py: generate_link_token()'s reuse check
      (server/hip_linking.py) needs to see a token saved by the actual
      running server process (which is what processes the
      on-generate-token callback via process_generate_token()), even
      when generate_link_token() itself is called from a different OS
      process (e.g. the M2 test CLI). An in-memory dict cannot do that;
      a shared file can.
    - Still not appropriate for real concurrent writers -- see
      json_file_store.py's own docstring.
    - Contains real link tokens (JWTs) -- gitignored, same as
      storage/api_capture.jsonl and storage/callbacks/*.

Future Implementation:
    - Redis
    - PostgreSQL
    - MongoDB
"""

from server.callbacks.utils.json_file_store import set_key, get_key, delete_key
from server.utils import generate_timestamp

_STORE_FILE = "patient_link_tokens.json"


# -----------------------------------------------------------------------------
# Save Patient Link Token
# -----------------------------------------------------------------------------

def save_patient_link_token(abha_address, link_token, hip_id):
    """
    Saves a patient's confirmed link token, keyed by ABHA address --
    matching how every other patient-keyed lookup in this codebase works
    (e.g. search_patient(abha_address=...)).

    Args:
        abha_address (str): Patient's ABHA address.
        link_token (str): The real link token confirmed via the
            on-generate-token callback.
        hip_id (str): The HIP identifier this token was issued under.

    Returns:
        None
    """

    set_key(
        _STORE_FILE,
        abha_address,
        {
            "link_token": link_token,
            "hip_id": hip_id,
            "received_at": generate_timestamp(),
        },
    )


# -----------------------------------------------------------------------------
# Get Patient Link Token
# -----------------------------------------------------------------------------

def get_patient_link_token(abha_address):
    """
    Retrieves a patient's saved link token.

    Args:
        abha_address (str): Patient's ABHA address.

    Returns:
        dict | None: {link_token, hip_id, received_at}, or None if
            nothing is saved for this patient.
    """

    return get_key(_STORE_FILE, abha_address)


# -----------------------------------------------------------------------------
# Delete Patient Link Token
# -----------------------------------------------------------------------------

def delete_patient_link_token(abha_address):
    """
    Deletes a patient's saved link token. Nothing currently calls this --
    included for completeness (e.g. a future path that learns a saved
    token was rejected/expired) since there's no confirmed signal today
    that would trigger it.

    Args:
        abha_address (str): Patient's ABHA address.

    Returns:
        bool
    """

    return delete_key(_STORE_FILE, abha_address)
