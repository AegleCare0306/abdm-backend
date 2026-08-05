"""
Repository for temporarily storing a pending Linking Care Context
request, so its on_carecontext callback (M2 doc §4.3.4) can auto-trigger
step 3 of the chain -- Notify Care Context Update (§4.3.6) -- for every
care context that was just linked.

The on_carecontext callback body only carries {abhaAddress, status,
error, response.requestId} -- it does NOT echo back which care contexts
were submitted, so that has to be stashed here before the outbound
link_care_context() call and read back once the callback confirms
success.

Current Implementation:
    - File-backed JSON storage under storage/pending_care_context_links.json
      (via server/callbacks/utils/json_file_store.py), NOT a plain
      in-memory dict -- same reasoning as link_token_repository.py and
      patient_link_token_repository.py: link_care_context() is called
      from two different OS processes (the auto-chained path inside the
      running `uvicorn server.main:app` process, and the M2 test CLI's
      reuse-token path as its own separate process), and whichever
      process receives ABDM's on_carecontext callback needs to read back
      whatever was saved, regardless of which process did the saving. A
      module-level dict is per-process state and would fail the same way
      the original link_token_repository.py did before that fix.
    - Still not appropriate for real concurrent writers -- see
      json_file_store.py's own docstring.
    - Still lost if storage/pending_care_context_links.json is
      deleted/corrupted (same category of gap as the other two
      file-backed stores).
    - Contains real link tokens and ABHA addresses -- gitignored, same
      as storage/pending_link_tokens.json and storage/patient_link_tokens.json.

Future Implementation:
    - Redis
    - PostgreSQL
    - MongoDB
"""

from server.callbacks.utils.json_file_store import set_key, get_key, delete_key

_STORE_FILE = "pending_care_context_links.json"


# -----------------------------------------------------------------------------
# Save Pending Care Context Link
# -----------------------------------------------------------------------------

def save_pending_care_context_link(request_id, session_data):
    """
    Saves a pending Linking Care Context request using the REQUEST-ID
    sent to ABDM as the key.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            link/carecontext call.
        session_data (dict): Pending care context link session
            information -- hip_id, abha_address, link_token,
            patient_reference, and care_context_hi_types (a
            {care_context_reference: [hi_type, ...]} map).

    Returns:
        None
    """

    set_key(_STORE_FILE, request_id, session_data)


# -----------------------------------------------------------------------------
# Get Pending Care Context Link
# -----------------------------------------------------------------------------

def get_pending_care_context_link(request_id):
    """
    Retrieves a stored pending care context link request.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            link/carecontext call.

    Returns:
        dict | None
    """

    return get_key(_STORE_FILE, request_id)


# -----------------------------------------------------------------------------
# Delete Pending Care Context Link
# -----------------------------------------------------------------------------

def delete_pending_care_context_link(request_id):
    """
    Deletes a pending care context link request.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            link/carecontext call.

    Returns:
        bool
    """

    return delete_key(_STORE_FILE, request_id)
