"""
Common utility functions for ABDM API requests.
"""

import uuid
import json
from datetime import datetime, timedelta, timezone

import requests

from server.callbacks.utils.flow_logger import log_phase, log_error

_token_cache = {
    "access_token": None,
    "expires_at": None,
}

def generate_request_id():
    """
    Generate a unique request ID for ABDM API calls.
    Returns:
        str: UUID string.
    """
    return str(uuid.uuid4())

def generate_timestamp():
    """
    Generate the current UTC timestamp in ISO 8601 format expected by ABDM APIs.
    Returns:
        str: UTC timestamp in ISO 8601 format.
    """
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )

def get_gateway_token():
    """
    Return a valid Gateway access token.
    If the cached token expires within the next 3 minutes, a new token is
    generated automatically.
    Returns:
        str: Gateway access token.
    Raises:
        requests.exceptions.RequestException: If the token request fails
            (network error or non-2xx response).
        KeyError: If the token response is missing expected fields.
    """

    from server.auth import generate_gateway_token

    now = datetime.now(timezone.utc)
    expires_at = _token_cache["expires_at"]

    refresh_required = (
        _token_cache["access_token"] is None
        or expires_at is None
        or now >= (expires_at - timedelta(minutes=3))
    )

    if refresh_required:
        # Token is about to expire. Generate a new one.
        try:
            response = generate_gateway_token()
            response.raise_for_status()
            data = response.json()
            _token_cache["access_token"] = data["accessToken"]
            _token_cache["expires_at"] = (
                now + timedelta(seconds=data["expiresIn"])
            )
            log_phase("Gateway token refreshed")
        except requests.exceptions.RequestException as exc:
            log_error(f"Gateway token request failed: {exc}")
            raise
        except (KeyError, ValueError) as exc:
            log_error(f"Gateway token response was malformed: {exc}")
            raise

    return _token_cache["access_token"]


def generate_expiry_time(minutes=5):
    """
    Generates an ISO 8601 UTC expiry timestamp.

    Args:
        minutes (int): Number of minutes from now until expiry.

    Returns:
        str: Expiry timestamp in ISO 8601 format.
    """

    expiry = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    return (
        expiry
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )



def generate_safe_past_timestamp(seconds=30):
    """
    Same format as generate_timestamp(), but a small fixed number of
    seconds in the past. Used for fields like doneAt where ABDM's
    validation appears to reject a timestamp that looks even slightly
    "in the future" -- which can happen from ordinary clock skew between
    our machine and ABDM's server, even when our system clock is correct.
    Returns:
        str: UTC timestamp in ISO 8601 format, `seconds` in the past.
    """

    past = datetime.now(timezone.utc) - timedelta(seconds=seconds)

    return (
        past
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def print_api_response(response):
    """
    Prints the complete HTTP response for debugging.

    Args:
        response: requests.Response object.
    """

    print("\n" + "=" * 60)
    print("ABDM API ERROR")
    print("=" * 60)

    print(f"Status Code : {response.status_code}")
    print(f"Reason      : {response.reason}")

    print("\nHeaders:")
    for key, value in response.headers.items():
        print(f"{key}: {value}")

    print("\nBody:")

    try:
        print(json.dumps(response.json(), indent=4))
    except ValueError:
        print(response.text)

    print("=" * 60)
