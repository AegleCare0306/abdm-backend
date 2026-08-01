"""
Shared runner for the OTP-based login variants.

7 of the 8 total login variants (all except "Login using Mobile Number")
follow the exact same shape: request_otp() -> prompt for OTP -> verify_otp()
-> parse {accounts, token}. They differ only in action/scope/loginHint/
otpSystem and the label shown when prompting for the raw identifier.

"Login using Mobile Number" (flows/login_mobile.py) has an extra T-Token ->
Verify User exchange after verify_otp() that doesn't fit this shape. It
reuses request_login_otp()/verify_login_otp() below for its shared OTP
request/verify steps, but stays a standalone module for the
account-selection + verify_user() steps.
"""

from server.abha import request_otp, verify_otp

from tools.m1_test_suite.common import (
    prompt,
    encrypt,
    print_header,
    print_info,
    print_success,
    print_failure,
    report_failure,
    print_accounts,
    log_response,
    redact_token,
)

MAX_OTP_ATTEMPTS = 3


def request_login_otp(action, scope, login_hint, login_id, otp_system, txn_id=""):
    """
    Calls request_otp(), prints the response's message, and returns the
    txnId to use for the following verify step -- or None on failure (the
    failure itself is already reported via report_failure()).

    txn_id: normally left as "" so ABDM mints a fresh one (matches
    request_otp()'s own default). Flows 8/9 (Search and Verify) instead
    pass the txnId carried over from the earlier Search ABHA Account step,
    per that doc's explicit instruction not to let a new one be minted.
    """
    print_info("Requesting OTP...")
    response = request_otp(
        action=action,
        scope=scope,
        login_hint=login_hint,
        login_id=login_id,
        otp_system=otp_system,
        txn_id=txn_id,
    )

    if response.status_code != 200:
        report_failure(response, "OTP request failed")
        return None

    body = response.json()
    print_success(body.get("message", "OTP requested."))
    return body.get("txnId", txn_id)


def verify_login_otp(action, scope, txn_id, expect_t_token=False):
    """
    Prompts for the OTP, encrypts it, calls verify_otp(), and parses the
    response. Tolerates two known response shapes rather than assuming
    the profile/login one is universal:

      - {"accounts": [...], "token": ...}  -- profile/login (Flows 2, 4, 5,
        and the T-Token step of Flow 3).
      - {"users": [...], "tokens": {"token": ...}}  -- phr/web/login/abha
        (live-confirmed for Flow 6; Flow 7 shares the same action family
        and almost certainly returns the same shape, but hasn't been
        separately confirmed live -- this works for it because the
        parsing below is shape-tolerant, not because that's been
        verified).

    Detection is shape-based (whichever fields are actually present),
    not an "if action == ..." branch -- this function stays
    action-agnostic, same as before.

    expect_t_token: True only for "Login using Mobile Number" (see that
    module's docstring). When True, this function labels the returned
    token as a T-Token in its printed output and skips the "Login
    succeeded" + account-list printing, since login isn't actually
    complete yet -- the caller still has an account-selection + Verify
    User exchange to do. It does NOT perform that exchange itself; the
    "x_token" key in the returned dict holds the T-Token in that case, and
    the caller is expected to overwrite it with the real X-Token once it
    has one.

    Returns {"x_token": ..., "accounts": ..., "txn_id": txn_id} either way
    -- the same normalized shape every flow module returns, regardless of
    which of the two raw response shapes above it came from.

    Always logs the full raw response body (via log_response(), to a file
    -- not the console, see that function) regardless of what was parsed
    out of it -- the same safety net enrollment.py's _print_outcome()
    already uses. This is exactly what caught the shape mismatch above: a
    live sandbox run of the phr/web/login/abha variant returned a 200 with
    accounts=[]/token=None under the old accounts/token-only parsing, with
    no way to tell from the console output alone whether that was
    genuinely empty or a differently-shaped response going unparsed.

    WRONG-OTP RETRY: ABDM can return HTTP 200 with a body that is actually
    a failure -- sandbox-confirmed from a real log entry (a deliberately
    wrong OTP during Flow 9):
        {"txnId": ..., "authResult": "failed",
         "message": "Please enter a valid OTP. Entered OTP is either
         expired or incorrect."}
    The response.status_code != 200 check below does NOT catch this (it's
    a 200), so this function separately checks body.get("authResult").
    Absent authResult is treated as success (not every response shape has
    been confirmed to carry this field -- both shapes seen live so far do,
    but treating "absent" as "OK, proceed" is the defensive choice for any
    shape that doesn't), so only an EXPLICIT non-"success" value counts as
    a failure. On that failure, the user is re-prompted for the OTP and
    verify_otp() is retried, up to MAX_OTP_ATTEMPTS total attempts,
    showing ABDM's own `message` each time. response.status_code != 200
    (an actual HTTP-level failure) is NOT retried -- that path is
    unchanged and returns immediately, same as before.
    """
    for attempt in range(1, MAX_OTP_ATTEMPTS + 1):
        if attempt == 1:
            otp_value = prompt("Enter the OTP you received")
        else:
            otp_value = prompt(f"Enter the OTP again (attempt {attempt}/{MAX_OTP_ATTEMPTS})")

        print_info("Verifying OTP...")
        response = verify_otp(
            action=action,
            scope=scope,
            txn_id=txn_id,
            otp_value=encrypt(otp_value),
        )

        if response.status_code != 200:
            report_failure(response, "OTP verification failed")
            return {"x_token": None, "accounts": [], "txn_id": txn_id}

        body = response.json()

        if body.get("authResult") not in (None, "success"):
            message = body.get("message", "OTP verification failed.")
            log_response(f"verify_otp response (action={action}, attempt={attempt}, FAILED)", body)
            if attempt < MAX_OTP_ATTEMPTS:
                print_failure(f"{message} ({MAX_OTP_ATTEMPTS - attempt} attempt(s) remaining -- try again.)")
                continue
            print_failure(f"{message} All {MAX_OTP_ATTEMPTS} attempts exhausted -- giving up.")
            return {"x_token": None, "accounts": [], "txn_id": txn_id}

        accounts = body.get("accounts") or body.get("users", [])
        token = body.get("token") or body.get("tokens", {}).get("token")

        if expect_t_token:
            print_info(f"T-Token received (short-lived -- needs a Verify User exchange, not usable directly): {redact_token(token)}")
        else:
            print_success("Login succeeded.")
            print_accounts(accounts)

        log_response(f"verify_otp response (action={action})", body)

        return {"x_token": token, "accounts": accounts, "txn_id": txn_id}


def run_login_variant(flow_title, identifier_label, action, scope, login_hint, otp_system):
    """
    Full run() body for a login variant that's just
    request_otp -> [OTP prompt] -> verify_otp with no extra steps -- covers
    5 of the 7 non-mobile login variants (Login using Aadhaar Number, both
    ABHA Number variants, both ABHA Address variants). Flows 8/9 (Search
    and Verify) don't use this directly since their loginId doesn't come
    from a fresh raw prompt -- they call request_login_otp()/
    verify_login_otp() themselves after their own Search step.
    """
    print_header(flow_title)

    raw_identifier = prompt(identifier_label)

    txn_id = request_login_otp(
        action=action,
        scope=scope,
        login_hint=login_hint,
        login_id=encrypt(raw_identifier),
        otp_system=otp_system,
    )

    if txn_id is None:
        return {"x_token": None, "accounts": [], "txn_id": None}

    return verify_login_otp(action=action, scope=scope, txn_id=txn_id)
