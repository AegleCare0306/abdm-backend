"""
Repository for persisting a patient's confirmed HIP-Initiated Linking
link token, keyed by (ABHA address, HIP id) TOGETHER, so it can be
reused across multiple care-context operations (Linking Care Context,
Notify Care Context Update) instead of calling ABDM's generate-token API
again for a patient who already has one -- but only when it's for the
SAME facility.

CONFIRMED REAL BUG (2026-08-05): this used to be keyed by abha_address
alone. A patient linked at one facility (e.g. Prithvi Health Solutions)
who was later selected at a DIFFERENT facility (e.g. MS Hospitals) hit
a real, live mismatch: generate_link_token() found the patient's token
from the first facility, logged a warning that it didn't match the
newly requested hip_id, and then silently proceeded to reuse it anyway
under the ORIGINAL facility -- discarding the facility and care-context
selections the caller had just made, with no way to opt out. A link
token is issued under a specific hip_id and isn't meaningful for a
different one; reusing across facilities was never actually correct.
Fixed by keying on (abha_address, hip_id) together: a saved token is
now only ever found and reused for the EXACT facility it was issued
under. A different facility for the same patient is treated as if no
token exists at all, and a brand-new one is generated for it (and saved
under its own key) -- this is now the standard behavior for any
patient/facility pair with no saved token, not a fallback or an edge
case. The hip_id-mismatch warning/log in generate_link_token() and the
CLI's reuse flow is no longer possible to hit and has been removed.

This is deliberately separate from link_token_repository.py, which
stores a PENDING session keyed by REQUEST-ID between the outbound
generate-token call and its on-generate-token callback, and is deleted
the moment that round-trip completes. This repository stores the
CONFIRMED result of that round-trip -- the real link token string --
keyed by the (patient, facility) pair it belongs to, for indefinite
reuse afterward.

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
    - File-backed, append-only JSON log under storage/patient_link_tokens.jsonl
      (via server/callbacks/utils/json_file_store.py), NOT a plain
      in-memory dict. File-backed since 2026-08-04 (so the M2 test CLI,
      a separate OS process from the running server, and the server
      share state); append-only since 2026-08-05 (see
      json_file_store.py's own docstring for why -- light concurrent
      testing, not a database-grade guarantee).
    - Contains real link tokens (JWTs) -- gitignored, same as
      storage/api_capture.jsonl and storage/callbacks/*.

Future Implementation:
    - Redis
    - PostgreSQL
    - MongoDB
"""

from server.callbacks.utils.json_file_store import set_key, get_key, delete_key
from server.utils import generate_timestamp

_STORE_FILE = "patient_link_tokens.jsonl"


def _composite_key(abha_address, hip_id):
    """
    A token is only ever valid for the exact facility it was issued
    under -- see the module docstring's 2026-08-05 bug writeup. Joined
    with a character ('|') that can't appear in either an ABHA address
    or a HIP id, so the two can't collide/be ambiguous with each other.
    """
    return f"{abha_address}|{hip_id}"


# -----------------------------------------------------------------------------
# Save Patient Link Token
# -----------------------------------------------------------------------------

def save_patient_link_token(abha_address, link_token, hip_id):
    """
    Saves a patient's confirmed link token, keyed by (ABHA address,
    HIP id) together -- a token issued under one facility is never
    returned for a lookup under a different one.

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
        _composite_key(abha_address, hip_id),
        {
            "link_token": link_token,
            "hip_id": hip_id,
            "received_at": generate_timestamp(),
        },
    )


# -----------------------------------------------------------------------------
# Get Patient Link Token
# -----------------------------------------------------------------------------

def get_patient_link_token(abha_address, hip_id):
    """
    Retrieves a patient's saved link token for a SPECIFIC facility. A
    token saved for a different facility for the same patient is not
    returned -- from this function's perspective, that's the same as
    no token existing at all, and the caller should generate a new one
    for this hip_id.

    Args:
        abha_address (str): Patient's ABHA address.
        hip_id (str): The HIP identifier a reusable token is needed
            for.

    Returns:
        dict | None: {link_token, hip_id, received_at}, or None if
            nothing is saved for this exact (patient, facility) pair.
    """

    return get_key(_STORE_FILE, _composite_key(abha_address, hip_id))


# -----------------------------------------------------------------------------
# Delete Patient Link Token
# -----------------------------------------------------------------------------

def delete_patient_link_token(abha_address, hip_id):
    """
    Deletes a patient's saved link token for a specific facility.
    Nothing currently calls this -- included for completeness (e.g. a
    future path that learns a saved token was rejected/expired) since
    there's no confirmed signal today that would trigger it.

    Args:
        abha_address (str): Patient's ABHA address.
        hip_id (str): The HIP identifier of the token to delete.

    Returns:
        bool
    """

    return delete_key(_STORE_FILE, _composite_key(abha_address, hip_id))
