"""
Flows 4 & 5 -- Login using ABHA Number.

Confirmed against the "Request OTP"/"Verify OTP" Implementation Matrices:

  Flow 4 -- OTP via Aadhaar Registered Mobile Number:
      action=profile/login, scope=["abha-login","aadhaar-verify"],
      loginHint=abha-number, otpSystem=aadhaar.

  Flow 5 -- OTP via ABHA Registered Mobile Number:
      action=profile/login, scope=["abha-login","mobile-verify"],
      loginHint=abha-number, otpSystem=abdm.

IMPORTANT DISTINCTION FROM "Login using Mobile Number" (flows/login_mobile.py):
Flow 5 shares its exact scope (["abha-login","mobile-verify"]) with the
mobile-number login variant that returns a T-Token, but this is NOT the
same behavior -- T-Token handling is only documented for loginHint=mobile
specifically, not for loginHint=abha-number even under the same scope.
Both flows here use the plain shared runner (expect_t_token defaults to
False inside it), so Verify OTP's "token" is treated as a direct, usable
X-Token. Do not collapse this with login_mobile.py's handling.
"""

from tools.m1_test_suite.login_runner import run_login_variant

ACTION = "profile/login"
LOGIN_HINT = "abha-number"
IDENTIFIER_LABEL = "ABHA Number (e.g. 91-1234-5678-9012)"


def run_aadhaar_registered_mobile():
    """Flow 4 -- Login using ABHA Number (OTP - Aadhaar Registered Mobile Number)."""
    return run_login_variant(
        flow_title="Flow 4: Login using ABHA Number (OTP - Aadhaar Registered Mobile Number)",
        identifier_label=IDENTIFIER_LABEL,
        action=ACTION,
        scope=["abha-login", "aadhaar-verify"],
        login_hint=LOGIN_HINT,
        otp_system="aadhaar",
    )


def run_abha_registered_mobile():
    """Flow 5 -- Login using ABHA Number (OTP - ABHA Registered Mobile Number)."""
    return run_login_variant(
        flow_title="Flow 5: Login using ABHA Number (OTP - ABHA Registered Mobile Number)",
        identifier_label=IDENTIFIER_LABEL,
        action=ACTION,
        scope=["abha-login", "mobile-verify"],
        login_hint=LOGIN_HINT,
        otp_system="abdm",
    )
