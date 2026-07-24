"""
Repository for temporarily storing ABDM Care Context linking sessions.

Current Implementation:
    - In-memory storage (for sandbox/testing)

Future Implementation:
    - Redis
    - PostgreSQL
    - MongoDB
"""

from copy import deepcopy

# -----------------------------------------------------------------------------
# In-Memory Storage
# -----------------------------------------------------------------------------

_link_sessions = {}


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

    _link_sessions[link_reference_number] = deepcopy(session_data)


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

    session = _link_sessions.get(link_reference_number)

    if session is None:
        return None

    return deepcopy(session)


# -----------------------------------------------------------------------------
# Update Link Session
# -----------------------------------------------------------------------------

def update_link_session(link_reference_number, updated_data):
    """
    Updates an existing link session.

    Args:
        link_reference_number (str): ABDM Link Reference Number.
        updated_data (dict): Data to update.

    Returns:
        bool
    """

    if link_reference_number not in _link_sessions:
        return False

    _link_sessions[link_reference_number].update(updated_data)

    return True


# -----------------------------------------------------------------------------
# Delete Link Session
# -----------------------------------------------------------------------------

def delete_link_session(link_reference_number):
    """
    Deletes a link session.

    Args:
        link_reference_number (str): ABDM Link Reference Number.

    Returns:
        bool
    """

    if link_reference_number in _link_sessions:
        del _link_sessions[link_reference_number]
        return True

    return False


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

    return link_reference_number in _link_sessions


# -----------------------------------------------------------------------------
# Get All Link Sessions (Debugging Only)
# -----------------------------------------------------------------------------

def get_all_link_sessions():
    """
    Returns all stored link sessions.

    Returns:
        dict
    """

    return deepcopy(_link_sessions)


# -----------------------------------------------------------------------------
# Clear All Link Sessions (Debugging Only)
# -----------------------------------------------------------------------------

def clear_all_link_sessions():
    """
    Clears all stored link sessions.

    Returns:
        None
    """

    _link_sessions.clear()