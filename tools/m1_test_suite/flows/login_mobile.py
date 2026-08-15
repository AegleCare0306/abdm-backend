"""
Flow 3 -- Login using Mobile Number (two-step).

Confirmed against the "Login using Mobile Number" Implementation Matrix row
(action=profile/login, scope=["abha-login","mobile-verify"],
loginHint=mobile, otpSystem=abdm) plus the "Verify User" documentation.

IMPORTANT: for this variant, Verify OTP's "token" field is a short-lived
T-Token, NOT the final session X-Token (confirmed in the Verify OTP doc's
"Important Values Returned" table) -- it must be passed to verify_user(),
not treated as a usable session token on its own. The real X-Token only
comes back from verify_user()'s response.

This is the ONE login variant that stays partially standalone rather than
using login_runner.run_login_variant() end to end: its OTP request/verify
steps reuse the shared request_login_otp()/verify_login_otp() helpers
(with expect_t_token=True), but the account-selection + Verify User
exchange afterward don't fit the shared "request -> verify -> done" shape,
so they stay here.
"""

from server.abha import verify_user

from tools.m1_test_suite.common import (
    prompt,
    encrypt,
    print_header,
    print_info,
    print_success,
    print_failure,
    log_response,
    redact_token,
    first_present,
    report_failure,
    select_account,
)
from tools.m1_test_suite.login_runner import request_login_otp, verify_login_otp

ACTION = "profile/login"
SCOPE = ["abha-login", "mobile-verify"]


def run():
    print_header("Flow 3: Login using Mobile Number")

    mobile_number = prompt("Mobile number (10 digits, no spaces/dashes)")

    txn_id = request_login_otp(
        action=ACTION,
        scope=SCOPE,
        login_hint="mobile",
        login_id=encrypt(mobile_number),
        otp_system="abdm",
    )

    if txn_id is None:
        return {"x_token": None, "accounts": [], "txn_id": None}

    verify_result = verify_login_otp(action=ACTION, scope=SCOPE, txn_id=txn_id, expect_t_token=True)
    t_token = verify_result["x_token"]  # actually a T-Token here, not a final X-Token -- see module docstring
    accounts = verify_result["accounts"]

    if t_token is None:
        return verify_result  # failure already reported by verify_login_otp()

    if not accounts:
        print_info("No accounts were returned -- cannot proceed to account selection.")
        return {"x_token": None, "accounts": [], "txn_id": txn_id}

    selected_account = select_account(accounts)
    abha_number = first_present(selected_account, "ABHANumber", "healthIdNumber")

    print_info(f"Selecting account: ABHA Number {abha_number}...")
    select_response = verify_user(
        t_token=t_token,
        action=ACTION,
        abha_number=abha_number,
        txn_id=txn_id,
    )

    if select_response.status_code != 200:
        report_failure(select_response, "Account selection (verify_user) failed")
        return {"x_token": None, "accounts": accounts, "txn_id": txn_id}

    select_body = select_response.json()
    x_token = select_body.get("token")

    # MISSING-TOKEN GUARD (edge-case-review pass, tracker case M1-14):
    # verify_login_otp() above already guards the T-Token step (a missing
    # 'token'/'tokens.token' there is reported as a failure, tracker case
    # M1-10). This verify_user() step has its own separate 'token' field
    # for the real X-Token, and the OLD code here printed "Login complete"
    # unconditionally even if x_token came back None -- misreporting a
    # login that produced no usable session token as a success, same bug
    # shape as M1-10 but one step later in this flow.
    if x_token is None:
        print_failure(
            "Account selection (verify_user) returned a 200/success response but no "
            "usable token was found under 'token' -- treating this as a failed login "
            "rather than reporting success with nothing to show for it."
        )
        log_response("verify_user response (MISSING token)", select_body)
        return {"x_token": None, "accounts": accounts, "txn_id": txn_id}

    print_success("Login complete for the selected account.")
    print_info(f"X-Token: {redact_token(x_token)}")
    log_response("verify_user response", select_body)

    return {"x_token": x_token, "accounts": accounts, "txn_id": txn_id}
