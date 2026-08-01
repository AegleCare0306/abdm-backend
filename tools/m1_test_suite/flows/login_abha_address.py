"""
Flows 6 & 7 -- Login using ABHA Address.

Confirmed against the "Request OTP"/"Verify OTP" Implementation Matrices:

  Flow 6 -- OTP via ABHA Registered Mobile Number:
      action=phr/web/login/abha, scope=["abha-address-login","mobile-verify"],
      loginHint=abha-address, otpSystem=abdm.

  Flow 7 -- OTP via Aadhaar Registered Mobile Number:
      action=phr/web/login/abha, scope=["abha-address-login","aadhaar-verify"],
      loginHint=abha-address, otpSystem=aadhaar.

Both use the plain shared runner -- no T-Token behavior is documented for
either of these.
"""

from tools.m1_test_suite.login_runner import run_login_variant

ACTION = "phr/web/login/abha"
LOGIN_HINT = "abha-address"
IDENTIFIER_LABEL = 'ABHA Address (e.g. "someone@sbx")'


def run_abha_registered_mobile():
    """Flow 6 -- Login using ABHA Address (OTP - ABHA Registered Mobile Number)."""
    return run_login_variant(
        flow_title="Flow 6: Login using ABHA Address (OTP - ABHA Registered Mobile Number)",
        identifier_label=IDENTIFIER_LABEL,
        action=ACTION,
        scope=["abha-address-login", "mobile-verify"],
        login_hint=LOGIN_HINT,
        otp_system="abdm",
    )


def run_aadhaar_registered_mobile():
    """Flow 7 -- Login using ABHA Address (OTP - Aadhaar Registered Mobile Number)."""
    return run_login_variant(
        flow_title="Flow 7: Login using ABHA Address (OTP - Aadhaar Registered Mobile Number)",
        identifier_label=IDENTIFIER_LABEL,
        action=ACTION,
        scope=["abha-address-login", "aadhaar-verify"],
        login_hint=LOGIN_HINT,
        otp_system="aadhaar",
    )
