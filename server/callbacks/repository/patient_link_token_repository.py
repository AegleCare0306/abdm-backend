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
under.

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
new one. No expiry/TTL enforcement is implemented here as a result: a
saved token is reused indefinitely until ABDM's real behavior is
confirmed otherwise. `received_at` is stored for future reference in
case that confirmation ever arrives. Flagged on the Notion "Needs ABDM
Spec Confirmation" tracker.

Current Implementation:
    - Postgres, via server/db.py + server/db_models.py:PatientLinkToken
      (P17, 2026-09-07) -- moved off the prior file-backed
      storage/patient_link_tokens.jsonl. `_composite_key()`'s own
      "{abha_address}|{hip_id}" string is kept EXACTLY as-is, stored in
      the table's single `composite_key` column -- not split into two
      columns + a composite unique constraint (that's a real improvement
      but a bigger redesign than this pass needs; a future cleanup can
      normalize it). See hiu_consent_repository.py's own banner for the
      full P16/P17 story (why Postgres, why now).
    - Every function's name, signature, and return contract is
      byte-for-byte identical to the file-backed version -- no caller
      outside this file needed to change.

Prior Implementation (superseded, see storage/patient_link_tokens.jsonl --
kept as an inert audit trail, not the live source of truth anymore):
    - File-backed, append-only JSON log (via
      server/callbacks/utils/json_file_store.py), NOT a plain in-memory
      dict. File-backed since 2026-08-04 (so the M2 test CLI, a separate
      OS process from the running server, and the server share state);
      append-only since 2026-08-05 (light concurrent testing, not a
      database-grade guarantee).

Future Implementation:
    - Normalize composite_key into (abha_address, hip_id) columns.
"""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from server.db import session_scope
from server.db_models import PatientLinkToken
from server.utils import generate_timestamp


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
    returned for a lookup under a different one. Upsert -- always
    overwrites any existing row for this composite key, same "no merge"
    contract the file-backed set_key() had.

    Args:
        abha_address (str): Patient's ABHA address.
        link_token (str): The real link token confirmed via the
            on-generate-token callback.
        hip_id (str): The HIP identifier this token was issued under.

    Returns:
        None
    """
    data = {
        "link_token": link_token,
        "hip_id": hip_id,
        "received_at": generate_timestamp(),
    }
    with session_scope() as session:
        stmt = pg_insert(PatientLinkToken).values(
            composite_key=_composite_key(abha_address, hip_id), data=data
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[PatientLinkToken.composite_key],
            set_={"data": stmt.excluded.data, "updated_at": func.now()},
        )
        session.execute(stmt)


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
    with session_scope() as session:
        row = (
            session.query(PatientLinkToken)
            .filter(PatientLinkToken.composite_key == _composite_key(abha_address, hip_id))
            .one_or_none()
        )
        return row.data if row is not None else None


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
    with session_scope() as session:
        deleted = (
            session.query(PatientLinkToken)
            .filter(PatientLinkToken.composite_key == _composite_key(abha_address, hip_id))
            .delete()
        )
        return deleted > 0
