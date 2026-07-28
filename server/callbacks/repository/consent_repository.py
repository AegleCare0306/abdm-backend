"""
Repository for temporarily storing granted Consent artifacts.

Current Implementation:
    - In-memory storage

Future:
    - Redis
    - PostgreSQL
"""

from copy import deepcopy

_consents = {}


def save_consent(
    consent_id,
    consent_data,
):
    """
    Stores a granted Consent artifact, keyed by consentId.
    """

    _consents[
        consent_id
    ] = deepcopy(consent_data)


def get_consent(
    consent_id,
):
    """
    Retrieves a stored Consent artifact. Returns None if not found
    (e.g. the consent was denied/revoked and never stored, or the
    consentId is unrecognized).
    """

    consent = _consents.get(
        consent_id
    )

    if consent is None:
        return None

    return deepcopy(consent)


def delete_consent(
    consent_id,
):
    """
    Deletes a stored Consent artifact.
    """

    if consent_id in _consents:
        del _consents[
            consent_id
        ]
        return True

    return False


def get_all_consents():
    """
    Debugging helper.
    """

    return deepcopy(
        _consents
    )
