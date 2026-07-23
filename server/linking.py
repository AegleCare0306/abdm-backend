import requests

from config import HIECM_BASE_URL, X_CM_ID
from utils import generate_request_id, generate_timestamp

def discover_patient(
    token,
    x_auth_token,
    hiu_id,
    hip_id,
    identifier_type,
    identifier_value,
):
    """
    Discover a patient for User Initiated Linking.
    Args:
        token (str): Gateway bearer token.
        x_auth_token (str): X-AUTH-TOKEN issued by ABDM.
        hiu_id (str): HIU identifier.
        hip_id (str): HIP identifier.
        identifier_type (str): Identifier type.
                               Example: "ABHA_ADDRESS"
        identifier_value (str): Identifier value.
    Returns:
        requests.Response
    """

    url = (
        f"{HIECM_BASE_URL}"
        "/user-initiated-linking/v3/patient/care-context/discover"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "X-AUTH-TOKEN": f"Bearer {x_auth_token}",
        "X-CM-ID": X_CM_ID,
        "X-HIU-ID": hiu_id,
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Content-Type": "application/json",
    }

    payload = {
        "hipId": hip_id,
        "unverifiedIdentifiers": [
            {
                "type": identifier_type,
                "value": identifier_value,
            }
        ],
    }

    response = requests.post(
        url=url,
        headers=headers,
        json=payload,
    )

    return response