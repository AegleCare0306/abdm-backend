"""
Repository for temporarily storing a pending Notify Care Context Update
request, so its on-notify callback (M2 doc §4.3.7) can retry the call
once if ABDM returns ABDM-1006 ("No links found for the patient in the
given HIP") -- a real, confirmed timing race (2026-08-04): the auto
Notify call fires ~190ms after Linking Care Context's own on_carecontext
success callback, which can be faster than ABDM's backend fully
propagating the new link before Notify's own validation runs. Two
manual retries 24s/40s later for the exact same patient/care context
both succeeded with no code change, supporting a timing explanation
over a data/logic bug.

The on-notify callback body only carries {requestId, timestamp,
acknowledgement, response.requestId, error} -- it does NOT echo back
what was actually notified, so that has to be stashed here before the
outbound notify_care_context_update() call and read back if a retry is
needed.

Current Implementation:
    - File-backed JSON storage under storage/pending_care_context_notifies.json
      (via server/callbacks/utils/json_file_store.py), same pattern as
      the other pending-session stores in this codebase.
    - Still not appropriate for real concurrent writers -- see
      json_file_store.py's own docstring.
    - Contains real link tokens and ABHA addresses -- gitignored, same
      as the other file-backed stores.

Future Implementation:
    - Redis
    - PostgreSQL
    - MongoDB
"""

from server.callbacks.utils.json_file_store import set_key, get_key, delete_key

_STORE_FILE = "pending_care_context_notifies.jsonl"


def save_pending_care_context_notify(request_id, session_data):
    """
    Saves a pending Notify Care Context Update request using the
    REQUEST-ID sent to ABDM as the key.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            link/context/notify call.
        session_data (dict): hip_id, abha_address, patient_reference,
            care_context_reference, hi_types, link_token, retry_count.

    Returns:
        None
    """

    set_key(_STORE_FILE, request_id, session_data)


def get_pending_care_context_notify(request_id):
    """
    Retrieves a stored pending Notify Care Context Update request.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            link/context/notify call.

    Returns:
        dict | None
    """

    return get_key(_STORE_FILE, request_id)


def delete_pending_care_context_notify(request_id):
    """
    Deletes a pending Notify Care Context Update request.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            link/context/notify call.

    Returns:
        bool
    """

    return delete_key(_STORE_FILE, request_id)
