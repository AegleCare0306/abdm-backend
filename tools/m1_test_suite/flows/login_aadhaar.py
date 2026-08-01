"""
Flow 2 -- Login using Aadhaar Number.

Confirmed against the "Request OTP" and "Verify OTP" Implementation
Matrices, "Login using Aadhaar Number" row:
    action=profile/login, scope=["abha-login","aadhaar-verify"],
    loginHint=aadhaar, otpSystem=aadhaar.

Uses the shared login_runner (see that module) -- this is one of the 7
login variants with no extra steps beyond request_otp -> OTP prompt ->
verify_otp.

FIELD-NAME NOTE (flagged, not silently guessed): "accounts" and "token" are
confirmed field names. The exact per-account keys for name/ABHA
Number/preferred ABHA Address were not given verbatim -- see
common.print_accounts()'s own docstring for that note (shared across every
login flow now).
"""

from tools.m1_test_suite.login_runner import run_login_variant


def run():
    return run_login_variant(
        flow_title="Flow 2: Login using Aadhaar Number",
        identifier_label="Aadhaar number (12 digits, no spaces/dashes)",
        action="profile/login",
        scope=["abha-login", "aadhaar-verify"],
        login_hint="aadhaar",
        otp_system="aadhaar",
    )
