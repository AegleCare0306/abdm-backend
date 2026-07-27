"""
Repository for temporarily storing Health Information Request sessions.

Current Implementation:
    - In-memory storage

Future:
    - Redis
    - PostgreSQL
"""

from copy import deepcopy

_health_information_sessions = {}


def save_health_information_session(
    transaction_id,
    session_data,
):
    """
    Stores a Health Information Request session.
    """

    _health_information_sessions[
        transaction_id
    ] = deepcopy(session_data)


def get_health_information_session(
    transaction_id,
):
    """
    Retrieves a stored Health Information Request session.
    """

    session = _health_information_sessions.get(
        transaction_id
    )

    if session is None:
        return None

    return deepcopy(session)


def update_health_information_session(
    transaction_id,
    updated_data,
):
    """
    Updates an existing session.
    """

    if transaction_id not in _health_information_sessions:
        return False

    _health_information_sessions[
        transaction_id
    ].update(updated_data)

    return True


def delete_health_information_session(
    transaction_id,
):
    """
    Deletes a stored session.
    """

    if transaction_id in _health_information_sessions:
        del _health_information_sessions[
            transaction_id
        ]
        return True

    return False


def get_all_health_information_sessions():
    """
    Debugging helper.
    """

    return deepcopy(
        _health_information_sessions
    )