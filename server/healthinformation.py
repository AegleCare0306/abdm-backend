import requests

from server.config import HIECM_BASE_URL
from server.utils import generate_request_id, generate_timestamp, get_gateway_token


def send_on_consent_notify(
    consent_id,
    request_id,
    status="OK",
):
    """
    Sends acknowledgement for Consent Notify callback.

    Args:
        consent_id (str)
        request_id (str)
        status (str)

    Returns:
        requests.Response
    """

    url = (
        f"{HIECM_BASE_URL}"
        "/consent/v3/request/hip/on-notify"
    )

    headers = {
        "Authorization": f"Bearer {get_gateway_token()}",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": "sbx",
        "Content-Type": "application/json",
    }

    payload = {
        "acknowledgement": {
            "status": status,
            "consentId": consent_id,
        },
        "response": {
            "requestId": request_id,
        },
    }

    response = requests.post(
        url=url,
        headers=headers,
        json=payload,
    )

    return response

def send_on_health_information_request(
    transaction_id,
    request_id,
    session_status="ACKNOWLEDGED",
):
    """
    Acknowledges receipt of a Health Information Request.

    Args:
        transaction_id (str)
        request_id (str)
        session_status (str)

    Returns:
        requests.Response
    """

    url = (
        f"{HIECM_BASE_URL}"
        "/data-flow/v3/health-information/hip/on-request"
    )

    headers = {
        "Authorization": f"Bearer {get_gateway_token()}",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": "sbx",
        "Content-Type": "application/json",
    }

    payload = {
        "hiRequest": {
            "transactionId": transaction_id,
            "sessionStatus": session_status,
        },
        "response": {
            "requestId": request_id,
        },
    }

    response = requests.post(
        url=url,
        headers=headers,
        json=payload,
    )

    return response