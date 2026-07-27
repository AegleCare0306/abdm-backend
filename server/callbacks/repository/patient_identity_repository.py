from copy import deepcopy


_patient_identity = {}


def save_patient_identity(
    abha_address,
    patient_data,
):
    """
    Stores patient identity information.

    Args:
        abha_address (str)
        patient_data (dict)
    """

    _patient_identity[abha_address] = deepcopy(patient_data)


def get_patient_identity(
    abha_address,
):
    """
    Retrieves patient identity information.

    Args:
        abha_address (str)

    Returns:
        dict | None
    """

    patient = _patient_identity.get(abha_address)

    if patient is None:
        return None

    return deepcopy(patient)