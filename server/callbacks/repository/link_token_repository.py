"""
Repository for temporarily storing pending HIP-Initiated Linking
link token requests.

Current Implementation:
    - File-backed JSON storage under storage/pending_link_tokens.json
      (via server/callbacks/utils/json_file_store.py), NOT a plain
      in-memory dict. CHANGED 2026-08-04: an in-memory dict was the
      original implementation, but that made a saved pending session
      invisible across OS process boundaries -- specifically, the M2
      test CLI (tools/m2_test_suite/cli.py) runs as its own separate
      process and calls generate_link_token() (server/hip_linking.py)
      directly, which is what actually saves a pending session here.
      The real running `uvicorn server.main:app` process -- a different
      OS process entirely -- is what receives ABDM's on-generate-token
      callback and needs to read that same pending session back. A
      module-level dict is per-process state; the callback handler's
      lookup failed 100% of the time as a result (confirmed via a real
      live test run, not a hypothetical). File-backed storage fixes this
      by giving both processes a shared place to read/write.
    - Still not appropriate for real concurrent writers -- see
      json_file_store.py's own docstring.
    - Still lost if storage/pending_link_tokens.json is deleted/corrupted
      (same category of gap as the old "lost on restart" in-memory
      limitation, just a different failure trigger).
    - Contains real link-token-request context (ABHA addresses) --
      gitignored, same as storage/api_capture.jsonl and
      storage/callbacks/*.

Future Implementation:
    - Redis
    - PostgreSQL
    - MongoDB
"""

from server.callbacks.utils.json_file_store import set_key, get_key, delete_key

_STORE_FILE = "pending_link_tokens.json"


# -----------------------------------------------------------------------------
# Save Pending Link Token
# -----------------------------------------------------------------------------

def save_pending_link_token(request_id, session_data):
    """
    Saves a pending link token request using the REQUEST-ID sent to ABDM
    as the key.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            generate-token call.
        session_data (dict): Pending link token session information.

    Returns:
        None
    """

    set_key(_STORE_FILE, request_id, session_data)


# -----------------------------------------------------------------------------
# Get Pending Link Token
# -----------------------------------------------------------------------------

def get_pending_link_token(request_id):
    """
    Retrieves a stored pending link token request.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            generate-token call.

    Returns:
        dict | None
    """

    return get_key(_STORE_FILE, request_id)


# -----------------------------------------------------------------------------
# Delete Pending Link Token
# -----------------------------------------------------------------------------

def delete_pending_link_token(request_id):
    """
    Deletes a pending link token request.

    Args:
        request_id (str): REQUEST-ID header value sent with the
            generate-token call.

    Returns:
        bool
    """

    return delete_key(_STORE_FILE, request_id)
