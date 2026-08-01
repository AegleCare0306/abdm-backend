"""
Authentication-related functions for ABDM APIs.
"""

import requests

from server.config import (
    CLIENT_ID,
    CLIENT_SECRET,
    GATEWAY_BASE_URL,
    X_CM_ID,
)

from server.utils import generate_request_id, generate_timestamp
from server.callbacks.utils.flow_logger import log_error
from server.callbacks.utils.api_capture import record_call

def generate_gateway_token():

    """
    Generate an ABDM Gateway access token.
    Returns:
        requests.Response: Gateway token response.
    Raises:
        requests.exceptions.RequestException: If the request fails
            (network error or non-2xx response).
    """

    url = f"{GATEWAY_BASE_URL}/sessions"

    payload = {
        "clientId": CLIENT_ID,
        "clientSecret": CLIENT_SECRET,
        "grantType": "client_credentials",
    }

    headers = {
        "Content-Type": "application/json",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
    }

    try:
        response = requests.post(
            url=url,
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        record_call(
            label="generate-gateway-token",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"Gateway token generation failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    record_call(
        label="generate-gateway-token",
        direction="outgoing",
        method="POST",
        url=url,
        request_headers=headers,
        request_body=payload,
        response_status=response.status_code,
        response_headers=dict(response.headers),
        response_body=response_body,
    )

    return response
