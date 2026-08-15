"""
Common utility functions for ABDM API requests.
"""

import threading
import time
import uuid
import json
from datetime import datetime, timedelta, timezone

import requests

from server.callbacks.utils.flow_logger import log_phase, log_error, log_retry

_token_cache = {
    "access_token": None,
    "expires_at": None,
}

# Race fix (edge-case-review pass, tracker case M1-3): get_gateway_token()
# reads _token_cache, and -- if refresh is needed -- makes a blocking
# network call and then writes BOTH _token_cache["access_token"] and
# _token_cache["expires_at"] back as two separate statements. Two logins
# landing close together could both see refresh_required=True before
# either one's writes land, then interleave their writes: e.g. thread A
# writes access_token=TOKEN_A, thread B then writes access_token=TOKEN_B
# followed immediately by expires_at=EXP_B, then thread A's own (now
# stale) expires_at=EXP_A write lands last -- leaving _token_cache holding
# TOKEN_B paired with EXP_A, a genuinely mismatched token/expiry pair that
# doesn't correspond to either real token response. A threading.Lock
# around the whole "check staleness, maybe refresh, write cache" sequence
# serializes concurrent callers within this one process, same pattern as
# server/crypto.py's certificate cache lock (tracker case M1-2) and
# json_file_store.py's per-file lock (tracker case M2-1).
_token_cache_lock = threading.Lock()

# -----------------------------------------------------------------------------
# Outbound call retry helper (retry-logic spec, 2026-08-14)
# -----------------------------------------------------------------------------
#
# WHY THIS EXISTS: every outbound call to ABDM in this codebase used to treat
# a transient failure (a network blip, ABDM having a bad second, a 5xx) the
# same as a permanent one -- reported as failed immediately, no retry. This
# gives transient failures a short, bounded retry window instead, while
# leaving every other outcome (a clean success, a genuine user-input error
# like a wrong OTP, or a non-transient "our own bug" response) completely
# untouched -- those are returned/raised on the very first attempt, exactly
# as if this wrapper weren't here.
#
# THREE-WAY FAILURE CLASSIFICATION, not two-way: every outbound call's
# failure is one of (1) a user-input error -- re-prompt, never auto-retry
# (e.g. wrong Aadhaar/OTP; ABDM told us the DATA was wrong, not that the
# call failed) -- unchanged by this wrapper, since retry logic never even
# sees these cases as "retry me"; (2) transient/retryable -- what this
# wrapper actually adds; (3) a non-transient server/client error that is NOT
# the user's fault (e.g. a 400 that isn't one of ABDM's documented
# validation-error shapes, usually a bug in how we built the request) --
# also unchanged; retrying it changes nothing (the same bad request goes out
# again) and re-prompting the user would be actively misleading. Getting a
# call site's classifier right matters more than the retry mechanics
# themselves -- see is_transient docs below and each call site's own
# comments for how that call's known failure modes were bucketed.
#
# DELIBERATELY GENERIC: this module knows nothing about any specific ABDM
# endpoint's response shapes -- only exception type and HTTP status code.
# Endpoint-specific knowledge (e.g. "this 400 shape means bad input, that
# one means our bug") stays in each call site's own code, not here.
_TRANSIENT_STATUS_CODES = {408, 429}


def _is_transient_failure(response, exception):
    """
    Default classifier for call_with_retry() -- deliberately the only
    generic signal available without any endpoint-specific knowledge:
    a connection-level failure (DNS, refused, reset), a timeout, or an
    HTTP response whose status is 5xx/429/408. Everything else (a 2xx
    success, a 4xx that isn't 408/429, or any other exception) is NOT
    transient -- call_with_retry() returns/raises it immediately on the
    first attempt.
    """
    if exception is not None:
        if isinstance(exception, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            return True
        # requests.exceptions.HTTPError (e.g. from response.raise_for_status())
        # carries the real Response on .response -- fall through to the
        # same status-code check used for a directly-returned response.
        response = getattr(exception, "response", None)
        if response is None:
            return False

    if response is None:
        return False

    return response.status_code in _TRANSIENT_STATUS_CODES or 500 <= response.status_code < 600


def call_with_retry(make_request, description, is_transient=_is_transient_failure,
                     max_attempts=3, delay_seconds=1.0):
    """
    Runs make_request() up to max_attempts times total (the original
    attempt plus up to max_attempts-1 retries), waiting delay_seconds
    (flat -- deliberately no backoff) between attempts, but ONLY when the
    outcome is classified as transient by is_transient(response,
    exception). Any non-transient outcome -- success, a user-input error,
    or a permanent/"our own bug" error -- stops the loop and is
    returned/raised on the spot, same as if this wrapper weren't used at
    all.

    Retry SCOPE is deliberately just this one call -- callers looping
    over several independent items (e.g. one fetch per consent artefact)
    should call this once per item, inside their own per-item try/except,
    not wrap the whole loop -- so one item's retries never delay or block
    another item's attempt.

    Every retry (and the final give-up, if attempts are exhausted while
    still transient) is logged via flow_logger.log_retry()/log_error() --
    no silent retries. Nothing is logged for the common case (success on
    the first attempt) or for a non-transient outcome, since the call
    site's own existing logging already covers those exactly as before.

    Args:
        make_request: Zero-arg callable performing ONE attempt of the
            outbound call (e.g. lambda: requests.post(url, ...)). May
            return a requests.Response, or raise -- most commonly
            requests.exceptions.RequestException, but any exception type
            is allowed through unchanged when non-transient.
        description: Short human-readable label used in retry/failure log
            lines (e.g. "Link token generation") -- never sent anywhere,
            only logged.
        is_transient: (response_or_None, exception_or_None) -> bool.
            Defaults to _is_transient_failure. Call sites with additional
            known-transient shapes (or that need to EXCLUDE a status code
            the default would otherwise treat as transient) can pass
            their own -- keeps endpoint-specific knowledge out of this
            shared module, per this section's own docstring.
        max_attempts: Total attempts including the first. Default 3 (the
            retry-logic spec's "3 attempts total": original + 2 retries).
        delay_seconds: Flat delay between attempts. Default 1.0 (the
            retry-logic spec's flat 1s -- worst case adds 2s per call,
            not counting each attempt's own request timeout).

    Returns:
        The response from whichever attempt stopped the loop (success or
        a non-transient failure), or the response from the final attempt
        if every attempt was transient.

    Raises:
        Whatever make_request() raised on the attempt that stopped the
        loop (immediately, if non-transient; after max_attempts, if every
        attempt raised a transient exception).
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            response = make_request()
        except Exception as exc:
            transient = is_transient(None, exc)
            if not transient or attempt >= max_attempts:
                if transient:
                    log_error(
                        f"{description}: still failing after {attempt} attempt(s) -- "
                        f"giving up. ({exc})"
                    )
                raise
            log_retry(
                f"{description}: attempt {attempt}/{max_attempts} failed ({exc}) -- "
                f"retrying in {delay_seconds}s..."
            )
            time.sleep(delay_seconds)
            continue

        if not is_transient(response, None) or attempt >= max_attempts:
            if is_transient(response, None):
                log_error(
                    f"{description}: still returning status {response.status_code} "
                    f"after {attempt} attempt(s) -- giving up."
                )
            return response

        log_retry(
            f"{description}: attempt {attempt}/{max_attempts} returned status "
            f"{response.status_code} -- retrying in {delay_seconds}s..."
        )
        time.sleep(delay_seconds)


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

    with _token_cache_lock:
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
                access_token = data["accessToken"]
                expires_in = data["expiresIn"]
                # MALFORMED-EXPIRY GUARD (edge-case-review pass, tracker
                # case M1-6): the OLD code passed expires_in straight into
                # timedelta(seconds=...) unchecked. A KeyError (field
                # missing) is caught below, but an unexpected VALUE for a
                # field that IS present -- None, a non-numeric string, a
                # bool, a list -- raises TypeError instead, which the old
                # except tuple (RequestException, KeyError, ValueError)
                # did NOT catch, crashing this call uncaught. Also guards
                # against a negative value, which timedelta() accepts
                # without error but which would immediately mark the
                # freshly "refreshed" token as already-expired. Checked
                # explicitly here so any of these malformed shapes fails
                # loud with a clear message instead of an unhandled
                # traceback (or a silently-broken cache).
                if not isinstance(expires_in, (int, float)) or isinstance(expires_in, bool) or expires_in <= 0:
                    raise ValueError(
                        f"'expiresIn' must be a positive number, got "
                        f"{type(expires_in).__name__}: {expires_in!r}"
                    )
                _token_cache["access_token"] = access_token
                _token_cache["expires_at"] = now + timedelta(seconds=expires_in)
                log_phase("Gateway token refreshed")
            except requests.exceptions.RequestException as exc:
                log_error(f"Gateway token request failed: {exc}")
                raise
            except (KeyError, ValueError, TypeError) as exc:
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
