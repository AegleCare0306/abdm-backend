"""
Cryptographic utilities for ABDM APIs.
Includes:
- Retrieving the ABDM public certificate.
- RSA encryption utilities.
"""

import base64
import uuid
import requests

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from server.config import ABHA_BASE_URL
from server.utils import generate_request_id, generate_timestamp, get_gateway_token
from server.callbacks.utils.flow_logger import log_phase, log_error
from server.callbacks.utils.api_capture import record_call

# -----------------------------------------------------------------------------
# Certificate Cache
# -----------------------------------------------------------------------------

_cached_certificate = None

def download_public_certificate():

    """
    Retrieve the ABDM public certificate.
    Returns:
        cryptography.hazmat.primitives.asymmetric.rsa.RSAPublicKey:
            Loaded RSA public key.
    Raises:
        requests.exceptions.RequestException: If the request fails
            (network error or non-2xx response).
        ValueError: If the response is missing the public key, or the
            key data is not valid PEM.
    """

    headers = {
        "Authorization": f"Bearer {get_gateway_token()}",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
    }

    url = f"{ABHA_BASE_URL}/profile/public/certificate"

    try:
        response = requests.get(
            url=url,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        record_call(
            label="get-public-certificate",
            direction="outgoing",
            method="GET",
            url=url,
            request_headers=headers,
            request_body=None,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"ABDM public certificate download failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    record_call(
        label="get-public-certificate",
        direction="outgoing",
        method="GET",
        url=url,
        request_headers=headers,
        request_body=None,
        response_status=response.status_code,
        response_headers=dict(response.headers),
        response_body=response_body,
    )

    public_key_str = response.json().get("publicKey")

    if not public_key_str:
        log_error("ABDM public certificate response did not include a publicKey.")
        raise ValueError("ABDM public certificate response is missing 'publicKey'.")

    public_key_str = public_key_str.strip()
    pem = (
        "-----BEGIN PUBLIC KEY-----\n"
        f"{public_key_str}\n"
        "-----END PUBLIC KEY-----\n"
    )

    try:
        public_key = serialization.load_pem_public_key(
            pem.encode("ascii")
        )
    except ValueError as exc:
        log_error(f"ABDM public certificate could not be parsed as PEM: {exc}")
        raise

    return public_key

def get_public_certificate():
    """
    Returns the cached ABDM public certificate.

    Downloads the certificate only if it has not
    already been cached.

    Returns:
        tuple:
            (
                public_certificate,
                key_id
            )
    """

    global _cached_certificate

    if _cached_certificate is None:

        certificate = download_public_certificate()

        _cached_certificate = certificate

        log_phase("ABDM public certificate downloaded")

    return (
        _cached_certificate
    )

def refresh_public_certificate():
    """
    Forces a fresh download of the ABDM
    public certificate.

    Returns:
        tuple
    """

    global _cached_certificate

    certificate = download_public_certificate()

    _cached_certificate = certificate

    log_phase("ABDM public certificate refreshed")

    return (
        _cached_certificate
    )

def clear_certificate_cache():
    """
    Clears the cached certificate.

    Returns:
        None
    """

    global _cached_certificate

    _cached_certificate = None

def encrypt_value(value, public_key):

    """
    Encrypt a value using RSA-OAEP with SHA-1 and return a Base64-encoded string.
    Args:
        value: The value to encrypt (string, int, float, etc.).
        public_key: Loaded RSA public key object.
    Returns:
        str: Base64-encoded encrypted string.
    Raises:
        ValueError: If public_key is None or encryption otherwise fails
            (e.g. the value is too large for the key size).
    """

    if public_key is None:
        log_error("encrypt_value() called with public_key=None -- was the certificate ever fetched?")
        raise ValueError("public_key is required for encryption but was None.")

    # Convert any input to a string.
    value = str(value)

    try:
        ciphertext = public_key.encrypt(
            value.encode("utf-8"),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA1()),
                algorithm=hashes.SHA1(),
                label=None,
            ),
        )
    except Exception as exc:
        log_error(f"RSA-OAEP encryption failed: {exc}")
        raise

    return base64.b64encode(ciphertext).decode("utf-8")
