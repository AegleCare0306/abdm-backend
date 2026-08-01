"""
Flow 1 -- ABHA Enrollment via Aadhaar.

Confirmed against the "Create ABHA by Aadhaar" and "Request OTP" ABDM
documentation. Two-step OTP flow: request an OTP against the (encrypted)
Aadhaar number, then submit it -- along with the user's plain mobile
number -- to complete enrollment.

FIELD-NAME NOTE (flagged, not silently guessed): the enrollment response's
"isNew", "mobile", and "mobileVerified" fields are confirmed by name in the
source documentation. The exact JSON key for "ABHA Number" in THIS specific
response was not given verbatim -- ABHANumber/healthIdNumber are both used
elsewhere in this codebase/ABDM's APIs for that concept, so both are tried
via first_present(), and the full raw response is always printed alongside
so nothing is lost if neither guess matches the real key.

RETURN DICT NOTE (Stage 3 addition): "mobile_number" -- the raw mobile
number the user actually typed at the prompt below -- was added to the
returned dict for flows/link_mobile.py (Flow 10) to chain off. It is
deliberately NOT the same thing as response.get("mobile"): the confirmed
behavior above is that "mobile" (and "mobileVerified") come back NULL in
the response in exactly the scenario Linking Mobile Number needs a mobile
number for, so there is nothing to reuse from the response body in that
case -- this locally-known value is the only place it's available.
"""

from server.abha import request_otp, enroll_by_aadhaar

from tools.m1_test_suite.common import (
    prompt,
    encrypt,
    print_header,
    print_info,
    print_success,
    print_failure,
    log_response,
    first_present,
    report_failure,
)


def run():
    print_header("Flow 1: ABHA Enrollment via Aadhaar")

    aadhaar_number = prompt("Aadhaar number (12 digits, no spaces/dashes)")
    mobile_number = prompt("Mobile number (used for enrollment; sent unencrypted -- see doc)")

    print_info("Requesting OTP...")
    otp_response = request_otp(
        action="enrollment",
        scope=["abha-enrol"],
        login_hint="aadhaar",
        login_id=encrypt(aadhaar_number),
        otp_system="aadhaar",
    )

    if otp_response.status_code != 200:
        report_failure(otp_response, "OTP request failed")
        return {"mobile_number": mobile_number}

    otp_body = otp_response.json()
    txn_id = otp_body.get("txnId")
    print_success(otp_body.get("message", "OTP requested."))

    otp_value = prompt("Enter the OTP you received")

    # OPEN QUESTION (not fixed in this pass -- do not assume either way):
    # verify_otp()'s equivalent 200-but-actually-failed wrong-OTP case
    # (authResult="failed" despite HTTP 200) was sandbox-confirmed and
    # given a retry loop in login_runner.verify_login_otp(). Whether
    # enroll_by_aadhaar() has an analogous 200-but-failed shape for a
    # wrong OTP here has NOT been confirmed live. No retry/authResult
    # handling has been added here on a guess -- a wrong OTP at this step
    # currently just flows through as whatever enroll_by_aadhaar() returns.
    print_info("Submitting OTP to complete enrollment...")
    enroll_response = enroll_by_aadhaar(
        txn_id=txn_id,
        # This is the one field deliberately NOT encrypted -- confirmed
        # from the documented request body: mobile is sent plain here,
        # unlike loginId/otpValue above.
        mobile=mobile_number,
        otp_value=encrypt(otp_value),
    )

    if enroll_response.status_code != 200:
        report_failure(enroll_response, "Enrollment failed")
        return {"txn_id": txn_id, "response": None, "mobile_number": mobile_number}

    enroll_body = enroll_response.json()
    _print_outcome(enroll_body)

    return {"txn_id": txn_id, "response": enroll_body, "mobile_number": mobile_number}


def _print_outcome(body):
    is_new = body.get("isNew")
    mobile_verified = body.get("mobileVerified")
    mobile = body.get("mobile")

    abha_number = first_present(body, "ABHANumber", "healthIdNumber")
    abha_address = first_present(body, "preferredAbhaAddress", "phrAddress")

    if mobile_verified is None and mobile is None:
        print_failure("Mobile number was not verified during enrollment.")
        print_info("Mobile verification is a separate flow (Stage 3) -- not handled here.")
    elif is_new is True:
        print_success("New ABHA created.")
    elif is_new is False:
        print_success("ABHA already existed for this Aadhaar (enrollment returned the existing account -- this is a normal success outcome, not an error).")
    else:
        print_info("Enrollment completed, but 'isNew' was not present in the response -- outcome unclear, see raw response below.")

    print_info(f"ABHA Number     : {abha_number}")
    print_info(f"ABHA Address    : {abha_address}")
    print_info(f"Mobile Verified : {mobile_verified}")
    log_response("enroll_by_aadhaar response", body)
