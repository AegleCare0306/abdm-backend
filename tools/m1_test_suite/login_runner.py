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
    prompt_digits,
    encrypt,
    print_header,
    print_info,
    print_success,
    print_failure,
    report_failure,
    print_accounts,
    log_response,
    redact_token,
    MAX_OTP_ATTEMPTS,
    MAX_IDENTIFIER_ATTEMPTS,
    is_aadhaar_gateway_unavailable,
    report_aadhaar_gateway_unavailable,
    classify_failure,
    RetryableIdentifierError,
)

# MAX_OTP_ATTEMPTS moved to common.py 2026-08-17 (now shared with
# enrollment.py's own OTP-retry loop, tracker case M1-16) -- imported
# above instead of being redefined here, so the two never drift apart.

# NOT-FOUND SIGNATURE (tracker: MS Testing Notes, 2026-08-18) -- confirmed
# real via a teammate's live sandbox run: entering an ABHA Number that
# doesn't exist returns HTTP 404 with this exact body shape. A genuinely
# unknown identifier is expected, normal behavior, not a bug -- this just
# gets it a clean message instead of a raw dump (see request_login_otp()).
_NOT_FOUND_SIGNATURE = {
    "match": lambda body: (
        isinstance(body, dict)
        and isinstance(body.get("error"), dict)
        and body["error"].get("code") == "ABDM-1114"
    ),
    "message": "No ABHA account was found for the identifier you entered. Please double-check it and try again.",
}

# 4 MORE SIGNATURES, all CONFIRMED via Aayush's own real sandbox run on
# 2026-08-18 (a "test a few more scenarios" follow-up pass -- see the
# api_capture/m1_2026-08-18.jsonl entries this was cross-checked against).
# All 4 currently raw-dump without these -- same "always fix clean-message
# issues" standing rule as _NOT_FOUND_SIGNATURE above.

# ABHA Address not-found: the phr/web/login/abha family (Flow 6/7) doesn't
# use the 404/ABDM-1114 shape above -- it uses a 400 with the SAME code
# (ABDM-9999) the gateway-outage check also uses, but a different message.
# Message-checked, not just code-checked, to avoid colliding with
# is_aadhaar_gateway_unavailable()'s own ABDM-9999 case (see that
# function's updated docstring/check in common.py).
_ABHA_ADDRESS_NOT_FOUND_SIGNATURE = {
    "match": lambda body: (
        isinstance(body, dict)
        and body.get("code") == "ABDM-9999"
        and str(body.get("message", "")).strip().lower() == "user not found"
    ),
    "message": "No ABHA account was found for the identifier you entered. Please double-check it and try again.",
}

# ABHA Number that's correctly-FORMATTED (passes prompt_abha_number()'s
# 14-digit check) but not a real/registered ABHA Number -- a different
# failure shape than the 404/ABDM-1114 case above, seen on Flow 4/5.
_LOGIN_ID_INVALID_SIGNATURE = {
    "match": lambda body: isinstance(body, dict) and body.get("loginId") == "LoginId is invalid",
    "message": "The ABHA Number you entered doesn't appear to be valid or registered. Please double-check it and try again.",
}

# Mobile number that's correctly-FORMATTED (passes prompt_digits()'s
# 10-digit check) but rejected by ABDM itself as not a valid mobile
# number -- seen on Flow 3's OTP-request step.
_INVALID_MOBILE_NUMBER_SIGNATURE = {
    "match": lambda body: isinstance(body, dict) and body.get("loginId") == "Invalid Mobile Number",
    "message": "The mobile number you entered doesn't appear to be valid. Please double-check it and try again.",
}

# Aadhaar number that's correctly-FORMATTED (12 digits) but not a real
# Aadhaar number per UIDAI -- seen on Flow 2's OTP-request step (loginHint
# ="aadhaar"). NOT the same as enrollment.py's _WRONG_OTP_SIGNATURE_ABDM_1204
# (also code ABDM-1204, but that one fires at the OTP-VERIFY step and means
# "wrong OTP" there -- this one fires at the OTP-REQUEST step and the
# message is explicit: UIDAI says the Aadhaar number itself is incorrect).
_AADHAAR_NUMBER_INCORRECT_SIGNATURE = {
    "match": lambda body: (
        isinstance(body, dict)
        and isinstance(body.get("error"), dict)
        and body["error"].get("code") == "ABDM-1204"
        and "aadhaar number is incorrect" in str(body["error"].get("message", "")).lower()
    ),
    "message": "The Aadhaar number you entered appears to be incorrect. Please double-check it and try again.",
}

_LOGIN_OTP_REQUEST_SIGNATURES = [
    _NOT_FOUND_SIGNATURE,
    _ABHA_ADDRESS_NOT_FOUND_SIGNATURE,
    _LOGIN_ID_INVALID_SIGNATURE,
    _INVALID_MOBILE_NUMBER_SIGNATURE,
    _AADHAAR_NUMBER_INCORRECT_SIGNATURE,
]

# WRONG-OTP, SECOND SHAPE (2026-08-18, same real-run follow-up): ABDM does
# NOT always return the 200/authResult="failed" shape verify_login_otp()
# already retries on -- a live run the same day showed a wrong (but
# correctly 6-digit) OTP can ALSO come back as a flat HTTP 400 with this
# body, even on a first verify attempt for a fresh txnId (confirmed --
# this is not just a stale-txnId-reuse artifact). Before this fix, that
# 400 fell into the generic "response.status_code != 200" branch and
# ABORTED the whole retry loop early -- the exact same "retry loop dies on
# a wrong-OTP shape it doesn't recognize" bug tracker case M1-16 (and this
# same MS-Testing-Notes follow-up) already fixed once for a DIFFERENT
# trigger (malformed-length OTP). The local prompt_digits() length guard
# added earlier does NOT fully close this -- it only stops a malformed
# OTP from ever being sent; it does nothing for a well-formed OTP that's
# simply wrong and happens to get this response shape instead of the
# other one. This is the actual, complete fix: treat this shape as an
# equally-valid "wrong OTP" signal and continue the retry loop on it, the
# same as the authResult="failed" case below.
_WRONG_OTP_INVALID_VALUE_SIGNATURE = {
    "match": lambda body: isinstance(body, dict) and body.get("otpValue") == "Invalid OTP Value",
    "message": "Incorrect OTP.",
}


def request_login_otp(action, scope, login_hint, login_id, otp_system, txn_id="", raise_on_retryable_identifier_error=False):
    """
    Calls request_otp(), prints the response's message, and returns the
    txnId to use for the following verify step -- or None on failure (the
    failure itself is already reported via report_failure()).

    raise_on_retryable_identifier_error (added 2026-08-18): when True, a
    match against _LOGIN_OTP_REQUEST_SIGNATURES (a wrong/unregistered
    Aadhaar, Mobile, ABHA Number, or ABHA Address) raises
    RetryableIdentifierError instead of just returning None -- lets a
    caller that wants to offer the user another attempt (see
    run_login_variant() below) catch it and re-prompt, instead of the
    flow silently quitting on a mistake the user can just fix. Defaults
    to False so existing callers that don't want this (link_mobile.py,
    login_search.py -- see their own modules for why) are unaffected.

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
        # AADHAAR-GATEWAY-UNAVAILABLE GUARD (tracker cases M1-16-adjacent,
        # confirmed 2026-08-18): only meaningful when THIS call actually
        # used otp_system="aadhaar" -- see
        # common.is_aadhaar_gateway_unavailable()'s docstring for how this
        # was confirmed real (a live outage, not a bug here) and why the
        # otp_system check matters (a 401 on a mobile-OTP call means
        # something different and must not be shown this message).
        if otp_system == "aadhaar" and is_aadhaar_gateway_unavailable(response):
            report_aadhaar_gateway_unavailable(response, "OTP request failed")
            return None
        # KNOWN-SIGNATURE CHECKS (2026-08-18, MS Testing Notes finding +
        # same-day follow-up real-run pass): a genuinely unknown/incorrect
        # identifier is a normal, expected outcome (not a bug), but was
        # showing the full raw ABDM error dump instead of a clean message
        # -- same "clean message required regardless of whether it's a
        # bug" rule as every other known-signature fix in this file. Not
        # status-code-gated (unlike the old 404-only check) -- each
        # signature in _LOGIN_OTP_REQUEST_SIGNATURES matches on its own
        # specific body shape, so classify_failure() only matches a real,
        # previously-confirmed shape regardless of which status code it
        # showed up under; anything else still falls through to the raw
        # dump, same as before.
        signature = classify_failure(response, _LOGIN_OTP_REQUEST_SIGNATURES)
        if signature is not None:
            print_failure(signature["message"])
            log_response(f"OTP request response (known failure signature, status {response.status_code})", response.json())
            if raise_on_retryable_identifier_error:
                raise RetryableIdentifierError(signature["message"])
            return None
        report_failure(response, "OTP request failed")
        return None

    # MALFORMED-BODY GUARD (edge-case-review pass, tracker case M1-5):
    # a 200 status only means the HTTP layer succeeded -- it says nothing
    # about the body actually being valid JSON. A broken/non-JSON body on
    # an otherwise-200 response (e.g. an HTML error page from a
    # misbehaving proxy/gateway in front of ABDM, or a truncated response)
    # used to crash here with an uncaught ValueError from response.json().
    # Same fix shape as the other malformed-response guards in this
    # module: log the raw text, report a clear failure, and return None
    # (this function's existing "failed" contract) instead of crashing.
    try:
        body = response.json()
    except ValueError as exc:
        print_failure(
            f"OTP request returned a 200 status but the response body wasn't valid "
            f"JSON ({exc}) -- treating this as a failed request rather than crashing."
        )
        log_response("OTP request response was not valid JSON", response.text)
        return None

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
        # LOCAL OTP-LENGTH GUARD (2026-08-18, MS Testing Notes finding): a
        # non-6-digit OTP ("1234", "12345") used to be sent to ABDM
        # unvalidated, which came back as an HTTP 400 ("Invalid OTP
        # Value") rather than the 200/authResult="failed" shape this
        # retry loop actually classifies -- so it fell into the
        # response.status_code != 200 branch below and ABORTED the whole
        # retry loop early (e.g. stopping after attempt 2/3) instead of
        # offering the remaining attempt(s). Rejecting/re-prompting
        # locally, exact-digit-allowlist, closes this at the source --
        # only a 6-digit numeric value is ever sent, so ABDM's real
        # wrong-OTP shape (200/authResult="failed") is the only failure
        # this loop should see going forward.
        label = "Enter the OTP you received" if attempt == 1 else f"Enter the OTP again (attempt {attempt}/{MAX_OTP_ATTEMPTS})"
        otp_value = prompt_digits(label, 6, "OTP")

        print_info("Verifying OTP...")
        response = verify_otp(
            action=action,
            scope=scope,
            txn_id=txn_id,
            otp_value=encrypt(otp_value),
        )

        if response.status_code != 200:
            # WRONG-OTP, SECOND SHAPE (2026-08-18) -- see
            # _WRONG_OTP_INVALID_VALUE_SIGNATURE's module-level comment
            # for the full story: this is a CONFIRMED-real wrong-OTP
            # response, not an HTTP-level failure, so it gets the same
            # retry treatment as the authResult="failed" shape below
            # instead of aborting the loop.
            signature = classify_failure(response, [_WRONG_OTP_INVALID_VALUE_SIGNATURE])
            if signature is not None:
                log_response(f"verify_otp response (action={action}, attempt={attempt}, FAILED, status {response.status_code})", response.json())
                if attempt < MAX_OTP_ATTEMPTS:
                    print_failure(f"{signature['message']} ({MAX_OTP_ATTEMPTS - attempt} attempt(s) remaining -- try again.)")
                    continue
                print_failure(f"{signature['message']} All {MAX_OTP_ATTEMPTS} attempts exhausted -- giving up.")
                return {"x_token": None, "accounts": [], "txn_id": txn_id}
            report_failure(response, "OTP verification failed")
            return {"x_token": None, "accounts": [], "txn_id": txn_id}

        # MALFORMED-BODY GUARD (tracker case M1-5) -- see the matching
        # guard in request_login_otp() above for the full rationale. Not
        # retried like a wrong-OTP failure (this isn't a user-input
        # problem, so re-prompting for the OTP again wouldn't help) --
        # reported as a failure immediately, same as an HTTP-level error.
        try:
            body = response.json()
        except ValueError as exc:
            print_failure(
                f"OTP verification returned a 200 status but the response body wasn't "
                f"valid JSON ({exc}) -- treating this as a failed verification rather "
                f"than crashing."
            )
            log_response(f"verify_otp response (action={action}) was not valid JSON", response.text)
            return {"x_token": None, "accounts": [], "txn_id": txn_id}

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

        # MALFORMED-SHAPE GUARDS (edge-case-review pass, tracker cases
        # M1-10/M1-12) -- both added here since both are "the response
        # parsed without raising, but what it parsed to isn't actually
        # usable" cases, same fix shape.
        #
        # M1-12: `accounts` is supposed to be a list of account dicts.
        # If ABDM ever returns it as plain text (or any other non-list
        # value) instead, the OLD code would pass it straight through to
        # print_accounts()/select_account(), which iterate it expecting
        # dicts -- for a string that means iterating individual
        # characters and crashing the CLI with an AttributeError the
        # first time `.get(...)` is called on one. Caught here instead,
        # at the one place every login variant's response flows through.
        if not isinstance(accounts, list):
            log_response(f"verify_otp response (action={action}, MALFORMED accounts/users field)", body)
            print_failure(
                f"OTP verification returned an 'accounts'/'users' field that isn't a list "
                f"(got {type(accounts).__name__}: {accounts!r}) -- treating this as no "
                f"accounts returned rather than crashing on it."
            )
            accounts = []

        # M1-10: a "tokens" section that's PRESENT but EMPTY (e.g.
        # `"tokens": {}`) parses to token=None here exactly like a
        # missing "tokens" section would -- `.get("token")` on an empty
        # dict is already safe, no crash either way. The actual bug was
        # one level up: with token=None, the OLD code still unconditionally
        # printed "Login succeeded." below, misreporting a login that
        # produced no usable token as a success. Checked explicitly here
        # so a missing/empty token is reported as a failure instead.
        if token is None:
            log_response(f"verify_otp response (action={action}, MISSING/EMPTY token)", body)
            print_failure(
                "OTP verification returned a 200/success response but no usable token "
                "was found under either 'token' or 'tokens.token' -- treating this as a "
                "failure rather than reporting a successful login with nothing to show for it."
            )
            return {"x_token": None, "accounts": accounts, "txn_id": txn_id}

        if expect_t_token:
            print_info(f"T-Token received (short-lived -- needs a Verify User exchange, not usable directly): {redact_token(token)}")
        else:
            print_success("Login succeeded.")
            print_accounts(accounts)

        log_response(f"verify_otp response (action={action})", body)

        return {"x_token": token, "accounts": accounts, "txn_id": txn_id}


def run_login_variant(flow_title, identifier_label, action, scope, login_hint, otp_system, identifier_validator=None):
    """
    Full run() body for a login variant that's just
    request_otp -> [OTP prompt] -> verify_otp with no extra steps -- covers
    5 of the 7 non-mobile login variants (Login using Aadhaar Number, both
    ABHA Number variants, both ABHA Address variants). Flows 8/9 (Search
    and Verify) don't use this directly since their loginId doesn't come
    from a fresh raw prompt -- they call request_login_otp()/
    verify_login_otp() themselves after their own Search step.

    identifier_validator (optional, added 2026-08-18): a no-arg callable
    that prompts and returns an already-validated raw identifier (e.g.
    common.prompt_aadhaar(...)/prompt_abha_number(...)/
    prompt_abha_address(...)), used instead of a plain prompt() when the
    field has a confirmed exact format. All 5 login variants that go
    through this function now pass one (see each flows/login_*.py module).

    IDENTIFIER-RETRY LOOP (added 2026-08-18, Aayush: "Incase of invalid
    mobile/aadhaar/abha display message and all to retry no quit"): if
    request_login_otp() raises RetryableIdentifierError (a known
    wrong/unregistered-identifier signature -- see that class's docstring
    in common.py), the user is re-prompted for the identifier and this
    retries up to MAX_IDENTIFIER_ATTEMPTS total, instead of the flow
    quitting on the first miss. An unrecognized failure shape, or the
    Aadhaar-gateway-unavailable case, still returns immediately (both
    already reported their own message) -- only a KNOWN, confirmed
    identifier-invalid signature is treated as retryable.
    """
    print_header(flow_title)

    for attempt in range(1, MAX_IDENTIFIER_ATTEMPTS + 1):
        raw_identifier = identifier_validator() if identifier_validator else prompt(identifier_label)

        try:
            txn_id = request_login_otp(
                action=action,
                scope=scope,
                login_hint=login_hint,
                login_id=encrypt(raw_identifier),
                otp_system=otp_system,
                raise_on_retryable_identifier_error=True,
            )
        except RetryableIdentifierError:
            if attempt < MAX_IDENTIFIER_ATTEMPTS:
                print_info(f"({MAX_IDENTIFIER_ATTEMPTS - attempt} attempt(s) remaining -- try again.)")
                continue
            print_failure(f"All {MAX_IDENTIFIER_ATTEMPTS} attempts exhausted -- giving up.")
            return {"x_token": None, "accounts": [], "txn_id": None}

        if txn_id is None:
            return {"x_token": None, "accounts": [], "txn_id": None}

        return verify_login_otp(action=action, scope=scope, txn_id=txn_id)
