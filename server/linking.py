import requests

from server.config import HIECM_BASE_URL, X_CM_ID
from server.utils import generate_request_id, generate_timestamp, get_gateway_token

def discover_patient(
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
        "Authorization": f"Bearer {get_gateway_token()}",
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

def send_on_discover(
    transaction_id,
    request_id,
    patient_data
):
    """
    Sends the on-discover response to ABDM Gateway.
    """

    url = (
        f"{HIECM_BASE_URL}"
        "/user-initiated-linking/v3/patient/care-context/on-discover"
    )

    payload = {
        "transactionId": transaction_id,
        "patient": patient_data,
        "matchedBy": ["MR"],
        "response": {
            "requestId": request_id
        }
    }

    headers = {
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_gateway_token()}",
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
    )

    print("\n===== ON DISCOVER RESPONSE =====")
    print("Status :", response.status_code)

    try:
        print(json.dumps(response.json(), indent=4))
    except Exception:
        print(response.text)

    return response

def send_on_init(
    transaction_id,
    request_id,
    link_reference_number,
    authentication_type,
    communication_medium,
    communication_hint,
    communication_expiry,
):
    """
    Sends the on-init response to the ABDM Gateway.
    """

    url = (
        f"{HIECM_BASE_URL}"
        "/user-initiated-linking/v3/link/care-context/on-init"
    )

    payload = {
        "transactionId": transaction_id,
        "link": {
            "referenceNumber": link_reference_number,
            "authenticationType": authentication_type,
            "meta": {
                "communicationMedium": communication_medium,
                "communicationHint": communication_hint,
                "communicationExpiry": communication_expiry,
            },
        },
        "response": {
            "requestId": request_id,
        },
    }

    headers = {
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_gateway_token()}",
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
    )

    return response

def send_on_confirm(
    patient,
    request_id,
):
    """
    Sends the ABDM on-confirm response.

    Args:
        patient (list): Patient array received during the Init callback.
        request_id (str): Request ID received in the Confirm callback.

    Returns:
        requests.Response
    """

    url = (
        f"{HIECM_BASE_URL}"
        "/user-initiated-linking/v3/link/care-context/on-confirm"
    )

    payload = {
        "patient": patient,
        "response": {
            "requestId": request_id
        }
    }

    headers = {
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_gateway_token()}",
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=30,
    )

    return response