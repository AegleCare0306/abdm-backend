"""
Repository for temporarily storing ABDM Care Context linking sessions
(UIL's Link Init -> Link Confirm chain), keyed by link_reference_number.

Current Implementation:
    - File-backed, append-only JSON log under storage/link_sessions.jsonl
      (via server/callbacks/utils/json_file_store.py) -- CHANGED
      2026-08-05, was a plain in-memory dict (T-80 on the To-Do Tracker).
      Same reasons as every other repository converted this way: a
      link session saved by one server process (e.g. before a
      `--reload` restart) was invisible to a later process, even though
      the gap between Link Init and Link Confirm "can be seconds or
      days" per the M2 flow docs -- a restart in that window silently
      broke the flow with nothing surfaced to ABDM. Concurrency-wise,
      same append-only middle ground as the other stores -- see
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

from server.callbacks.utils.json_file_store import set_key, get_key, delete_key, get_all

_STORE_FILE = "link_sessions.jsonl"


# -----------------------------------------------------------------------------
# Save Link Session
# -----------------------------------------------------------------------------

def save_link_session(link_reference_number, session_data):
    """
    Saves a link session using the link reference number as the key.

    Args:
        link_reference_number (str): ABDM Link Reference Number.
        session_data (dict): Link session information.

    Returns:
        None
    """

    set_key(_STORE_FILE, link_reference_number, deepcopy(session_data))


# -----------------------------------------------------------------------------
# Get Link Session
# -----------------------------------------------------------------------------

def get_link_session(link_reference_number):
    """
    Retrieves a stored link session.

    Args:
        link_reference_number (str): ABDM Link Reference Number.

    Returns:
        dict | None
    """

    session = get_key(_STORE_FILE, link_reference_number)

    if session is None:
        return None

    return deepcopy(session)


# -----------------------------------------------------------------------------
# Update Link Session
# -----------------------------------------------------------------------------

def update_link_session(link_reference_number, updated_data):
    """
    Updates an existing link session (read-modify-write at the
    application level -- appends one new full-value line to the log,
    same as every other write here). Returns False without writing
    anything if the session doesn't currently exist.

    Args:
        link_reference_number (str): ABDM Link Reference Number.
        updated_data (dict): Data to update.

    Returns:
        bool
    """

    session = get_key(_STORE_FILE, link_reference_number)

    if session is None:
        return False

    session = dict(session)
    session.update(updated_data)
    set_key(_STORE_FILE, link_reference_number, session)

    return True


# -----------------------------------------------------------------------------
# Delete Link Session
# -----------------------------------------------------------------------------

def delete_link_session(link_reference_number):
    """
    Deletes a stored link session (appends a delete tombstone -- see
    json_file_store.py). Returns True if the session existed
    immediately before this call, False otherwise.

    Args:
        link_reference_number (str): ABDM Link Reference Number.

    Returns:
        bool
    """

    return delete_key(_STORE_FILE, link_reference_number)


# -----------------------------------------------------------------------------
# Check if Link Session Exists
# -----------------------------------------------------------------------------

def link_session_exists(link_reference_number):
    """
    Checks if a link session exists.

    Args:
        link_reference_number (str): ABDM Link Reference Number.

    Returns:
        bool
    """

    return get_key(_STORE_FILE, link_reference_number) is not None


# -----------------------------------------------------------------------------
# Get All Link Sessions (Debugging Only)
# -----------------------------------------------------------------------------

def get_all_link_sessions():
    """
    Returns all stored link sessions.

    Returns:
        dict
    """

    return deepcopy(get_all(_STORE_FILE))


# -----------------------------------------------------------------------------
# Clear All Link Sessions (Debugging Only)
# -----------------------------------------------------------------------------

def clear_all_link_sessions():
    """
    Clears all stored link sessions -- appends a delete tombstone for
    every key currently present. Best-effort: the append-only log
    design has no true "truncate" operation, so this grows the file
    rather than shrinking it. Debugging only; no caller in this
    codebase today.

    Returns:
        None
    """

    for key in get_all(_STORE_FILE):
        delete_key(_STORE_FILE, key)
