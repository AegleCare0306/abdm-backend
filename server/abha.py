"""
ABHA-related APIs.
Contains APIs for OTP requests and ABHA enrollment workflows.
"""

import time

import requests
from server.config import ABHA_BASE_URL
from server.utils import generate_request_id, generate_timestamp, get_gateway_token, call_with_retry
from server.callbacks.utils.flow_logger import log_error
from server.callbacks.utils.api_capture import record_call


def _post(url, headers, payload, action_description):
    """
    Shared request wrapper -- every function in this module makes a very
    similar POST call. Catches connection-level failures (DNS, timeout,
    connection refused) so they're logged with context instead of
    surfacing as a bare traceback. Does NOT call raise_for_status() here,
    since callers of these functions expect to inspect response.status_code
    themselves (e.g. a non-200 OTP response is an expected, handled case,
    not an exceptional one).

    RETRY: category 2 (transient/retryable) here is ONLY a connection
    error/timeout, or a 5xx/429/408 response -- see
    server/utils.py's call_with_retry(). This module never calls
    raise_for_status(), so ABDM's own "wrong OTP"/validation-error shapes
    (category 1: user-input error) always come back as a normal 200/400
    response, not an exception -- those are NOT transient by the default
    classifier and are returned on the first attempt exactly as before,
    completely untouched. In particular, the wrong-OTP-retry loop in
    tools/m1_test_suite/login_runner.py (verify_login_otp(), which
    re-prompts the user based on response.status_code/authResult) never
    sees a difference: it only ever gets called after _post() has already
    settled on a final response, transient or not.

    IDEMPOTENCY (unconfirmed, flagged per the retry-logic spec rather
    than assumed): several of this module's endpoints consume a
    single-use txnId/OTP (enroll_by_aadhaar, verify_otp,
    verify_mobile_linking_otp). If a connection error/timeout happens
    AFTER ABDM actually received and processed the request but BEFORE we
    saw the response, our retry resubmits the same txnId/OTP a second
    time. Whether ABDM's real sandbox treats a same-txnId resubmission as
    safe (idempotent no-op / same result) or rejects it (e.g. "OTP
    already used") is NOT confirmed anywhere in this codebase's docs or
    comments -- flagging this explicitly, matching this codebase's own
    convention (see server/auth.py's update_bridge_url() docstring) for
    an unconfirmed-but-documented assumption, rather than guessing either
    way. Only matters for the network-exception path -- a same-OTP retry
    caused by ABDM returning a 5xx/429/408 (a response we DID receive)
    is not this ambiguity, since we know ABDM never accepted that attempt.
    """
    try:
        response = call_with_retry(
            lambda: requests.post(url=url, headers=headers, json=payload, timeout=30),
            description=action_description,
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label=action_description,
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"{action_description} failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    record_call(
        label=action_description,
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


def request_otp(
    action,
    scope,
    login_hint,
    login_id,
    otp_system="aadhaar",
    txn_id="",
    x_token=None,
):

    """
    Request an OTP for an ABDM workflow.
    Args:
        action (str): profile/login, enrollment, etc.
        scope (list): API scope.
        login_hint (str): aadhaar, mobile, abha-number, etc.
        login_id (str): Usually an encrypted value.
        otp_system (str): aadhaar, mobile, etc.
        txn_id (str, optional): Transaction ID if required.
        x_token (str, optional): User X-Token.
    Returns:
        requests.Response
    """

    url = f"{ABHA_BASE_URL}/{action}/request/otp"

    headers = {
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "Content-Type": "application/json",
    }

    if x_token:
        headers["X-Token"] = f"Bearer {x_token}"

    payload = {
        "scope": scope,
        "loginHint": login_hint,
        "loginId": login_id,
        "otpSystem": otp_system,
        "txnId": txn_id,
    }

    return _post(url, headers, payload, f"OTP request ({action})")

def enroll_by_aadhaar(
    txn_id,
    otp_value,
    mobile,
    consent_code="abha-enrollment",
    consent_version="1.4",
):

    """
    Complete ABHA enrollment using Aadhaar OTP.
    Args:
        txn_id (str): Transaction ID returned by request_otp().
        otp_value (str): RSA encrypted OTP.
        mobile (str): Mobile number.
        consent_code (str): Consent code.
        consent_version (str): Consent version.
    Returns:
        requests.Response
    """

    url = f"{ABHA_BASE_URL}/enrollment/enrol/byAadhaar"

    headers = {
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "Content-Type": "application/json",
    }

    payload = {
        "authData": {
            "authMethods": ["otp"],
            "otp": {
                "timeStamp": generate_timestamp(),
                "txnId": txn_id,
                "otpValue": otp_value,
                "mobile": mobile,
            },
        },
        "consent": {
            "code": consent_code,
            "version": consent_version,
        },
    }

    return _post(url, headers, payload, "ABHA enrollment by Aadhaar")

def create_abha_address(
    action,
    txn_id,
    abha_address,
    preferred=1,
):

    """
    Create a custom ABHA Address during ABDM enrollment.
    Args:
        action (str): API path after /v3/.
            Example: "enrollment/enrol"
        txn_id (str): Transaction ID from the enrollment flow.
        abha_address (str): Custom ABHA Address to create.
        preferred (int): 1 to mark this as the account's preferred
            address, 0 otherwise. Default is 1.
    Returns:
        requests.Response
    """

    url = f"{ABHA_BASE_URL}/{action}/abha-address"

    headers = {
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "Content-Type": "application/json",
    }

    payload = {
        "txnId": txn_id,
        "abhaAddress": abha_address,
        "preferred": preferred,
    }

    return _post(url, headers, payload, "ABHA Address creation")

def request_email_verification_link(
    x_token,
    action,
    scope,
    login_hint,
    login_id,
    otp_system="abdm",
):

    """
    Request an email verification link for an ABDM workflow.
    Args:
        x_token (str): User X-Token.
        action (str): API path after /v3/.
            Example: "profile/account"
        scope (list): Workflow scope.
        login_hint (str): Usually "email".
        login_id (str): Encrypted email address.
        otp_system (str): OTP system. Default is "abdm".
    Returns:
        requests.Response
    """

    url = f"{ABHA_BASE_URL}/{action}/request/emailVerificationLink"

    headers = {
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-Token": f"Bearer {x_token}",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Content-Type": "application/json",
    }

    payload = {
        "scope": scope,
        "loginHint": login_hint,
        "loginId": login_id,
        "otpSystem": otp_system,
    }

    return _post(url, headers, payload, "Email verification link request")

def verify_mobile_linking_otp(
    action,
    scope,
    txn_id,
    otp_value,
    auth_method="otp",
):

    """
    Verify OTP to Link Mobile using the ABDM authentication service.
    Args:
        action (str): API path after /v3/, WITHOUT the trailing "/auth"
            (this function appends "/auth/byAbdm" itself below).
            Example: "enrollment" -> POSTs to .../enrollment/auth/byAbdm
        scope (list): Workflow scope.
            Example: ["abha-enrol", "mobile-verify"]
        txn_id (str): Transaction ID returned by request_otp().
        otp_value (str): RSA encrypted OTP.
        auth_method (str): Authentication method. Default is "otp".
    Returns:
        requests.Response
    """

    url = f"{ABHA_BASE_URL}/{action}/auth/byAbdm"

    headers = {
        "Authorization": f"Bearer {get_gateway_token()}",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Content-Type": "application/json",
    }

    payload = {
        "scope": scope,
        "authData": {
            "authMethods": [auth_method],
            "otp": {
                "timeStamp": generate_timestamp(),
                "txnId": txn_id,
                "otpValue": otp_value,
            },
        },
    }

    return _post(url, headers, payload, "Mobile linking OTP verification")

def verify_otp(action,
    scope,
    txn_id,
    otp_value,
    auth_method="otp",
    x_token=None,
):

    """
    Verify an OTP for an ABDM workflow.
    Args:
        action (str): API path after /v3/.
            Examples:
                "profile/login"
                "profile/account"
        scope (list): Workflow scope.
            Examples:
                ["abha-login", "aadhaar-verify"]
                ["account-delete"]
        txn_id (str): Transaction ID returned by request_otp().
        otp_value (str): RSA encrypted OTP.
        auth_method (str): Authentication method. Default is "otp".
        x_token (str, optional): User X-Token.
    Returns:
        requests.Response
    """

    url = f"{ABHA_BASE_URL}/{action}/verify"

    headers = {
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "Content-Type": "application/json",
    }

    if x_token:
        headers["X-Token"] = f"Bearer {x_token}"

    payload = {
        "scope": scope,
        "authData": {
            "authMethods": [auth_method],
            "otp": {
                "txnId": txn_id,
                "otpValue": otp_value,
            },
        },
    }

    return _post(url, headers, payload, f"OTP verification ({action})")

def verify_user(
    t_token,
    action,
    abha_number,
    txn_id,
):

    """
    Verify the selected ABHA user for an ABDM workflow.
    Args:
        token (str): Gateway bearer token.
        t_token (str): Temporary T-Token returned during login.
        action (str): API path after /v3/.
            Example: "profile/login"
        abha_number (str): Selected ABHA number.
        txn_id (str): Transaction ID.
    Returns:
        requests.Response
    """

    url = f"{ABHA_BASE_URL}/{action}/verify/user"

    headers = {
        "Authorization": f"Bearer {get_gateway_token()}",
        "T-Token": f"Bearer {t_token}",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Content-Type": "application/json",
    }

    payload = {
        "ABHANumber": abha_number,
        "txnId": txn_id,
    }

    return _post(url, headers, payload, "ABHA user verification")

def search_abha_by_mobile(
    action,
    scope,
    mobile,
):

    """
    Search for ABHA accounts using a mobile number.
    Args:
        action (str): API path after /v3/.
            Example: "profile/account"
        scope (list): Workflow scope.
            Example: ["search-abha"]
        mobile (str): RSA encrypted mobile number.
    Returns:
        requests.Response
    """

    url = f"{ABHA_BASE_URL}/{action}/abha/search"

    headers = {
        "Authorization": f"Bearer {get_gateway_token()}",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Content-Type": "application/json",
    }

    payload = {
        "scope": scope,
        "mobile": mobile,
    }

    return _post(url, headers, payload, "ABHA search by mobile")

def search_abha_by_address(
    action,
    abha_address,
):

    """
    Search for an ABHA account using an ABHA Address.
    Args:
        action (str): API path after /v3/.
            Example: "phr/web/login"
        abha_address (str): ABHA Address to search.
    Returns:
        requests.Response
    """

    url = f"{ABHA_BASE_URL}/{action}/abha/search"

    headers = {
        "Authorization": f"Bearer {get_gateway_token()}",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Content-Type": "application/json",
    }

    payload = {
        "abhaAddress": abha_address,
    }

    return _post(url, headers, payload, "ABHA search by address")

_DOWNLOAD_WALL_CLOCK_TIMEOUT = 30  # seconds -- matches every other outbound call's timeout=30 convention


def _download_with_wall_clock_timeout(url, headers, resource_label, max_seconds=_DOWNLOAD_WALL_CLOCK_TIMEOUT):
    """
    GETs `url`, enforcing `max_seconds` as a genuine TOTAL wall-clock
    deadline on the download -- not the per-read gap `requests`' own
    `timeout=` parameter actually bounds (tracker case M1-24).

    WHY: `requests.get(..., timeout=30)` -- even for a plain,
    non-streaming call like get_resource()'s original version -- only
    bounds the gap BETWEEN individual socket reads under the hood
    (urllib3 applies the read timeout per chunk read, not once for the
    whole response). A response that trickles in a few bytes every
    <30s (e.g. a misbehaving proxy in front of ABDM, or just a slow
    connection on a large ABHA card image) never triggers that
    per-chunk timeout and can hang effectively forever, even though the
    call site asked for `timeout=30`.

    FIX: stream=True + iter_content() with an explicit
    time.monotonic() deadline checked between chunks -- the only way to
    bound TOTAL call duration rather than inter-byte gaps. Manually
    re-populates response._content/_content_consumed the same way
    requests' own Response.content property does internally (see its
    source: `self._content = b"".join(self.iter_content(...))`), so
    every caller of get_resource() (get_profile/get_qr_code/
    get_abha_card and their own callers) keeps working exactly as
    before -- .json()/.text/.content on the returned Response object
    are unaffected by this change.
    """
    response = requests.get(url=url, headers=headers, timeout=max_seconds, stream=True)

    deadline = time.monotonic() + max_seconds
    chunks = []
    for chunk in response.iter_content(chunk_size=8192):
        if chunk:
            chunks.append(chunk)
        if time.monotonic() > deadline:
            response.close()
            raise requests.exceptions.Timeout(
                f"{resource_label}: download exceeded {max_seconds}s total wall-clock time "
                f"(slow-loris style response -- bytes kept arriving just under the per-chunk "
                f"timeout without the download ever completing)"
            )

    response._content = b"".join(chunks)
    response._content_consumed = True
    return response


def get_resource(
    x_token,
    action="profile/account",
    resource=None,
):

    """
    Retrieve an ABDM resource.
    Args:
        x_token (str): User X-Token.
        action (str): API path after /v3/.
            Default: "profile/account"
        resource (str, optional): Resource to retrieve.
            Examples:
                None -> Profile
                "qrCode" -> QR Code
                "abha-card" -> ABHA Card
    Returns:
        requests.Response
    """

    url = f"{ABHA_BASE_URL}/{action}"

    if resource:
        url = f"{url}/{resource}"

    headers = {
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-Token": f"Bearer {x_token}",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
    }

    resource_label = f"get-resource ({action}{'/' + resource if resource else ''})"

    # RETRY: category 2 is a connection error/timeout or a 5xx/429/408
    # response -- see call_with_retry(). Read-only GET (profile/QR/card
    # download) -- trivially safe to retry.
    try:
        response = call_with_retry(
            lambda: _download_with_wall_clock_timeout(url, headers, resource_label),
            description=resource_label,
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label=resource_label,
            direction="outgoing",
            method="GET",
            url=url,
            request_headers=headers,
            request_body=None,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"ABDM resource retrieval ({action}{'/' + resource if resource else ''}) failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    record_call(
        label=resource_label,
        direction="outgoing",
        method="GET",
        url=url,
        request_headers=headers,
        request_body=None,
        response_status=response.status_code,
        response_headers=dict(response.headers),
        response_body=response_body,
    )

    return response

def get_profile(x_token, action="profile/account"):
    return get_resource(x_token, action=action)

def get_qr_code(x_token, action="profile/account"):
    return get_resource(x_token, action=action, resource="qrCode")

def get_abha_card(x_token, action="profile/account"):
    return get_resource(x_token, action=action, resource="abha-card")
