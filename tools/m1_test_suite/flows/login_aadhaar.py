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
from tools.m1_test_suite.common import prompt_aadhaar

_LABEL = "Aadhaar number (12 digits -- dashes/spaces OK)"


def run():
    # LOCAL INPUT-VALIDATION GUARD (2026-08-18, MS Testing Notes finding,
    # UPDATED later same day per Aayush's revised rule): a non-12-digit
    # and a non-numeric Aadhaar number were both previously sent to ABDM
    # unvalidated, coming back as a raw "LoginId is invalid" 400 dump --
    # now rejected/re-prompted locally. Originally strict digit-only
    # (prompt_digits), UPDATED to prompt_aadhaar() which also accepts
    # dash-separated/space-separated input and strips it -- Aayush:
    # "Aadhaar and ABHA should handle all scenarios... we accept
    # everything and send the required format" (supersedes the plain
    # exact-match-allowlist rule for this field specifically).
    return run_login_variant(
        flow_title="Flow 2: Login using Aadhaar Number",
        identifier_label=_LABEL,
        action="profile/login",
        scope=["abha-login", "aadhaar-verify"],
        login_hint="aadhaar",
        otp_system="aadhaar",
        identifier_validator=lambda: prompt_aadhaar(_LABEL),
    )
