"""
Flow 10 -- Linking Mobile Number.

Confirmed against the "Linking Mobile Number" and "Request OTP" docs.
Chains off a FRESH ABHA ENROLLMENT (Flow 1), not a login -- this workflow
only applies when enrollment's own mobile number differs from the
Aadhaar-linked one (enrollment already showed mobile/mobileVerified as
null in exactly that scenario).

DEVIATION FROM THE LITERAL TASK TEXT (flagged, not silently guessed): the
task said to reuse the mobile number "from the enrollment response's
'mobile' field". But enrollment.py's own already-confirmed finding is
that BOTH 'mobile' and 'mobileVerified' come back NULL in the response in
exactly the scenario this flow needs a mobile number for -- so there is
nothing to reuse from the response body in that case. Instead,
enrollment.run()'s returned dict was extended with a new "mobile_number"
key (the raw value the user actually typed) -- see enrollment.py's own
note -- and THAT is what's reused here.

Uses login_runner.request_login_otp() for the OTP-request step (it's
action/scope-agnostic), but NOT verify_login_otp()/verify_otp() for the
verify step -- this workflow's completion endpoint is a DIFFERENT one from
the generic Verify OTP: server.abha.verify_mobile_linking_otp() already
exists specifically because of that.

ACTION-VALUE FIX (2026-08-01): verify_mobile_linking_otp() builds its URL
as f"{ABHA_BASE_URL}/{action}/auth/byAbdm" -- so the confirmed endpoint
".../enrollment/auth/byAbdm" requires action="enrollment", NOT
action="enrollment/auth" (which produced a double "auth" in the URL).
The function's own docstring example was misleading and has been
corrected too (server/abha.py). Verified against the real doc's endpoint
string directly, not guessed.
"""

from server.abha import verify_mobile_linking_otp

from tools.m1_test_suite.flows import enrollment
from tools.m1_test_suite.common import (
    prompt,
    encrypt,
    print_header,
    print_info,
    print_success,
    print_failure,
    log_response,
    report_failure,
)
from tools.m1_test_suite.login_runner import request_login_otp

ACTION = "enrollment"
SCOPE = ["abha-enrol", "mobile-verify"]


def run():
    print_header("Flow 10: Linking Mobile Number")

    print_info("Running a fresh ABHA enrollment first (this flow chains off one)...")
    enrollment_result = enrollment.run()

    txn_id = enrollment_result.get("txn_id")
    response = enrollment_result.get("response")
    mobile_number = enrollment_result.get("mobile_number")

    if not txn_id or not response:
        print_failure("Enrollment did not complete successfully -- nothing to link.")
        return {"linked": False, "txn_id": txn_id}

    mobile_verified = response.get("mobileVerified")

    if mobile_verified:
        print_success("Mobile number is already verified via the Aadhaar-linked number -- Linking Mobile Number is not needed.")
        return {"linked": False, "txn_id": txn_id}

    if not mobile_number:
        print_failure("No mobile number available to link (none captured during enrollment) -- cannot proceed.")
        return {"linked": False, "txn_id": txn_id}

    print_info(f"Mobile not verified during enrollment -- requesting a new OTP to link mobile number {mobile_number}...")

    otp_txn_id = request_login_otp(
        action=ACTION,
        scope=SCOPE,
        login_hint="mobile",
        login_id=encrypt(mobile_number),
        otp_system="abdm",
    )

    if otp_txn_id is None:
        return {"linked": False, "txn_id": txn_id}

    otp_value = prompt("Enter the OTP you received")

    print_info("Verifying mobile-linking OTP...")
    verify_response = verify_mobile_linking_otp(
        action="enrollment",
        scope=SCOPE,
        txn_id=otp_txn_id,
        otp_value=encrypt(otp_value),
    )

    if verify_response.status_code != 200:
        report_failure(verify_response, "Mobile linking failed")
        return {"linked": False, "txn_id": otp_txn_id}

    body = verify_response.json()

    # Same 200-but-actually-failed pattern verify_login_otp() was fixed
    # for -- checked here too, but deliberately WITHOUT a retry loop
    # (explicitly optional/nice-to-have per the task, not required for
    # this lower-traffic flow): a wrong OTP here just fails this run;
    # re-running the flow (which re-runs enrollment too) tries again.
    if body.get("authResult") not in (None, "success"):
        message = body.get("message", "Mobile linking OTP verification failed.")
        print_failure(message)
        log_response("verify_mobile_linking_otp response (FAILED)", body)
        return {"linked": False, "txn_id": otp_txn_id}

    abha_number = body.get("ABHANumber")
    print_success(body.get("message", "Mobile number linked successfully."))
    print_info(f"ABHA Number: {abha_number}")
    log_response("verify_mobile_linking_otp response", body)

    return {"linked": True, "abha_number": abha_number, "txn_id": otp_txn_id}
