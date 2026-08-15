"""
Cryptographic utilities for ABDM APIs.
Includes:
- Retrieving the ABDM public certificate.
- RSA encryption utilities.
"""

import base64
import threading
import time
import uuid
import requests

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from server.config import ABHA_BASE_URL
from server.utils import generate_request_id, generate_timestamp, get_gateway_token, call_with_retry
from server.callbacks.utils.flow_logger import log_phase, log_error
from server.callbacks.utils.api_capture import record_call

# -----------------------------------------------------------------------------
# Certificate Cache
# -----------------------------------------------------------------------------

_cached_certificate = None
_cached_at = None

# TTL fix (edge-case-review pass, tracker case M1-1): refresh_public_certificate()
# and clear_certificate_cache() existed but had zero call sites -- if ABDM
# ever rotates this certificate, a long-running server process would stay
# broken (silently succeeding locally against the stale key, then failing
# on ABDM's side) until someone manually restarted it. There's no local
# signal that tells us a rotation happened (the failure shows up as a
# generic ABDM-side decrypt error, not something distinguishable here),
# so this doesn't attempt to *detect* rotation -- it bounds the staleness
# window instead: the cache is now allowed to go stale for at most
# _CERTIFICATE_TTL_SECONDS before the next get_public_certificate() call
# forces a fresh download, same as if refresh_public_certificate() had
# been called. This is a real, generically-useful fix (any process using
# this module self-heals within the TTL window without a restart), not a
# full fix for "detect a rotation the instant it happens" -- that would
# need ABDM to expose a signal we don't currently have.
_CERTIFICATE_TTL_SECONDS = 24 * 60 * 60  # 24 hours

# Race fix (edge-case-review pass, tracker case M1-2): two logins landing
# at (almost) the exact same moment could both see the cache as empty/stale
# before either one finished writing it back, so both would call
# download_public_certificate() -- at best a wasted duplicate download, at
# worst (thread A downloads and writes _cached_certificate, then thread B's
# own download overwrites it, then thread A's own `return _cached_certificate`
# executes afterward) thread A can end up returning a DIFFERENT certificate
# object than the one it itself just downloaded. A plain threading.Lock
# around the whole "check staleness, maybe download, write cache" sequence
# below serializes concurrent callers within this one process, same pattern
# as json_file_store.py's per-file lock (tracker case M2-1).
_cache_lock = threading.Lock()

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

    RETRY: category 2 is a connection error/timeout or a 5xx/429/408
    response -- see server/utils.py's call_with_retry(). This is a
    background, read-only lookup -- trivially safe to retry. Composes
    with get_public_certificate()'s own TTL cache/lock unchanged: the
    retry loop runs entirely inside this one download, still fully
    inside _cache_lock, before the cache is ever written -- a caller
    waiting on the lock just waits slightly longer on a transient blip,
    same as it already would for a slow single attempt.
    """

    headers = {
        "Authorization": f"Bearer {get_gateway_token()}",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
    }

    url = f"{ABHA_BASE_URL}/profile/public/certificate"

    try:
        def _attempt():
            response = requests.get(
                url=url,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            return response

        response = call_with_retry(_attempt, description="ABDM public certificate download")
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

    Downloads the certificate if it has not already been cached, or if
    the cached copy has exceeded _CERTIFICATE_TTL_SECONDS -- see that
    constant's own comment for why this exists (bounds how long a
    rotated-but-undetected certificate can stay stale, rather than
    caching forever with no refresh path ever exercised).

    Returns:
        tuple:
            (
                public_certificate,
                key_id
            )
    """

    global _cached_certificate, _cached_at

    with _cache_lock:
        is_stale = (
            _cached_at is not None
            and (time.monotonic() - _cached_at) >= _CERTIFICATE_TTL_SECONDS
        )

        if _cached_certificate is None or is_stale:

            certificate = download_public_certificate()

            _cached_certificate = certificate
            _cached_at = time.monotonic()

            log_phase(
                "ABDM public certificate refreshed (TTL expired)"
                if is_stale else
                "ABDM public certificate downloaded"
            )

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

    global _cached_certificate, _cached_at

    certificate = download_public_certificate()

    _cached_certificate = certificate
    _cached_at = time.monotonic()

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

    global _cached_certificate, _cached_at

    _cached_certificate = None
    _cached_at = None

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
