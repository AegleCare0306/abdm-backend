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

import requests

from server.abha import request_otp, enroll_by_aadhaar

from tools.m1_test_suite.common import (
    prompt,
    prompt_digits,
    prompt_aadhaar,
    encrypt,
    print_header,
    print_info,
    print_success,
    print_failure,
    log_response,
    first_present,
    report_failure,
    report_connection_error,
    classify_failure,
    MAX_OTP_ATTEMPTS,
    is_aadhaar_gateway_unavailable,
    report_aadhaar_gateway_unavailable,
)

# WRONG-OTP SIGNATURE (tracker case M1-16 -- CONFIRMED via a live sandbox
# run 2026-08-17 + Aayush's direct confirmation of what it means). Unlike
# the login flows (a wrong OTP comes back as HTTP 200 with
# authResult="failed" -- see login_runner.verify_login_otp()),
# enroll_by_aadhaar() returns an HTTP 400 with body
# {"mobile": "Invalid Mobile Number", ...} for a wrong OTP. ABDM's own
# label here is genuinely misleading -- the actual cause is the OTP, not
# the mobile field -- but this exact signature has now been confirmed to
# mean "wrong OTP" at THIS specific endpoint. Used below to show a clean
# retry message instead of dumping the raw response to the console.
#
# Any OTHER/unrecognized failure at this step is NOT assumed to be this --
# it still falls through to report_failure()'s full raw dump and is NOT
# retried (Aayush, 2026-08-17: "if the reason is known always the clean
# message should be displayed, for a new scenario the dump can be
# displayed so I know a reason to be added for that scenario").
_WRONG_OTP_SIGNATURE = {
    "match": lambda body: isinstance(body, dict) and body.get("mobile") == "Invalid Mobile Number",
    "message": "Incorrect OTP.",
}

# SECOND WRONG-OTP SIGNATURE (tracker case M1-16, reopened 2026-08-17):
# a live run against the real sandbox on 2026-08-17 showed ABDM does NOT
# always return the "Invalid Mobile Number" shape above for a wrong OTP
# at this endpoint -- this run instead got HTTP 422 with
# {"error": {"code": "ABDM-1204", "message": "UIDAI Error code : 400 :
# OTP validation failed"}}. That first signature match failed on this
# shape (it only checks the "mobile" field), so the retry loop fell
# through to the raw-dump/not-retried branch even though this is, if
# anything, a MORE explicit wrong-OTP indicator than the first one.
# Added as a second, independently-matched signature rather than
# replacing the first, since both shapes have now been observed for
# real from the live sandbox.
_WRONG_OTP_SIGNATURE_ABDM_1204 = {
    "match": lambda body: (
        isinstance(body, dict)
        and isinstance(body.get("error"), dict)
        and body["error"].get("code") == "ABDM-1204"
    ),
    "message": "Incorrect OTP.",
}


def run():
    print_header("Flow 1: ABHA Enrollment via Aadhaar")

    # LOCAL INPUT-VALIDATION GUARD (2026-08-18, MS Testing Notes finding on
    # Flow 2, same underlying field/gap): both fields now rejected/
    # re-prompted locally on anything but the exact expected digit count,
    # instead of being sent to ABDM unvalidated and coming back as a raw
    # "LoginId is invalid"/"Invalid Mobile Number" dump.
    # UPDATED 2026-08-18 (Aayush's revised rule -- see common.prompt_aadhaar()
    # docstring): Aadhaar now accepts dash-separated/space-separated input
    # too, not just plain digits.
    aadhaar_number = prompt_aadhaar("Aadhaar number (12 digits -- dashes/spaces OK)")
    mobile_number = prompt_digits("Mobile number (used for enrollment; sent unencrypted -- see doc)", 10, "Mobile number")

    print_info("Requesting OTP...")
    # CONNECTION-ERROR GUARD (tracker case M1-21, partial -- the OTP
    # REQUEST step; see the enroll_by_aadhaar() call below for the OTP
    # SUBMIT step, which is where the plan's actual "Wi-Fi drops right
    # after typing the OTP" scenario lands): a RequestException here
    # (call_with_retry exhausted) previously propagated uncaught to
    # cli.py's generic top-level handler. Caught here instead so the
    # user gets an honest message about what's actually known/unknown,
    # not just "some flow raised an unexpected error".
    try:
        otp_response = request_otp(
            action="enrollment",
            scope=["abha-enrol"],
            login_hint="aadhaar",
            login_id=encrypt(aadhaar_number),
            otp_system="aadhaar",
        )
    except requests.exceptions.RequestException as exc:
        report_connection_error(exc, "OTP request failed with a connection error")
        return {"mobile_number": mobile_number}

    if otp_response.status_code != 200:
        # AADHAAR-GATEWAY-UNAVAILABLE GUARD (confirmed 2026-08-18) -- this
        # flow always requests with otp_system="aadhaar" (see the request_otp
        # call above), so no extra otp_system check is needed here unlike
        # login_runner.py's shared request_login_otp(), which serves both
        # aadhaar and mobile-based flows. See common.py's
        # is_aadhaar_gateway_unavailable() docstring for how this was
        # confirmed real (a live ABDM-side outage, not a bug here).
        if is_aadhaar_gateway_unavailable(otp_response):
            report_aadhaar_gateway_unavailable(otp_response, "OTP request failed")
            return {"mobile_number": mobile_number}
        report_failure(otp_response, "OTP request failed")
        return {"mobile_number": mobile_number}

    otp_body = otp_response.json()
    txn_id = otp_body.get("txnId")
    print_success(otp_body.get("message", "OTP requested."))

    # MISSING-TXNID GUARD (edge-case-review pass, tracker case M1-15): the
    # OLD code trusted txn_id unconditionally, even though otp_body.get()
    # silently returns None if "txnId" is absent from the response. That
    # None would then flow straight into enroll_by_aadhaar(txn_id=None,
    # ...), sending a literal "txnId": null to ABDM instead of failing
    # fast locally with a clear message -- the same "parsed without
    # raising, but not actually usable" shape as the accounts/token
    # guards already added to login_runner.verify_login_otp() for M1-10/
    # M1-12. Caught here instead, before the OTP prompt even happens, so
    # the user isn't asked to enter an OTP for a transaction that was
    # never actually opened.
    if not txn_id:
        print_failure(
            "OTP request returned a 200/success response but no 'txnId' was found in "
            "the body -- cannot proceed to submit an OTP without a transaction ID."
        )
        log_response("request_otp response (enrollment, MISSING txnId)", otp_body)
        return {"mobile_number": mobile_number}

    # WRONG-OTP RETRY (tracker case M1-16, fixed 2026-08-17): a wrong OTP
    # at this step is now a CONFIRMED, classified failure (see
    # _WRONG_OTP_SIGNATURE above) -- on a match, show a clean "Incorrect
    # OTP" message and let the user retry, up to MAX_OTP_ATTEMPTS, same UX
    # as the login flows' authResult="failed" retry loop. Any other
    # failure shape is NOT retried and still shows the full raw dump (see
    # the signature comment above for why).
    for attempt in range(1, MAX_OTP_ATTEMPTS + 1):
        # LOCAL OTP-LENGTH GUARD (2026-08-18) -- see the matching guard in
        # login_runner.py's verify_login_otp() for the full rationale
        # (MS Testing Notes finding: a non-6-digit OTP used to abort this
        # retry loop early via an unclassified raw 400 instead of being
        # caught locally).
        label = "Enter the OTP you received" if attempt == 1 else f"Enter the OTP again (attempt {attempt}/{MAX_OTP_ATTEMPTS})"
        otp_value = prompt_digits(label, 6, "OTP")

        print_info("Submitting OTP to complete enrollment...")
        # CONNECTION-ERROR GUARD (tracker cases M1-21/M1-22): this is the
        # exact call both cases are about -- a network drop right after
        # typing the OTP (M1-21), or a proxy that withholds the response
        # past the client timeout while ABDM actually completes the
        # enrollment server-side (M1-22). Before this, a RequestException
        # here propagated uncaught to cli.py's generic top-level handler,
        # which prints only "Flow 1... raised an unexpected error:
        # ConnectionError: ..." -- zero statement about whether the
        # enrollment might have actually gone through, so a tester would
        # naturally just re-run the flow, hit ABDM's "already exists"
        # response on the second attempt, and see
        # _print_outcome()'s `is_new is False` branch print a calm "this is
        # a normal success outcome" message -- technically true, but it
        # masks that the FIRST, timed-out attempt is the one that actually
        # created the account (M1-22's exact concern). report_connection_error()
        # says explicitly that this outcome is unknown rather than implying
        # either "nothing happened" or silently mismessaging it as a normal
        # retry later. Not retried -- a connection error isn't a user-input
        # problem, so re-prompting for the OTP again wouldn't help.
        try:
            enroll_response = enroll_by_aadhaar(
                txn_id=txn_id,
                # This is the one field deliberately NOT encrypted -- confirmed
                # from the documented request body: mobile is sent plain here,
                # unlike loginId/otpValue above.
                mobile=mobile_number,
                otp_value=encrypt(otp_value),
            )
        except requests.exceptions.RequestException as exc:
            report_connection_error(exc, "Enrollment submission failed with a connection error")
            return {"txn_id": txn_id, "response": None, "mobile_number": mobile_number}

        if enroll_response.status_code != 200:
            signature = classify_failure(enroll_response, [_WRONG_OTP_SIGNATURE, _WRONG_OTP_SIGNATURE_ABDM_1204])
            if signature is not None:
                log_response(f"enroll_by_aadhaar response (attempt={attempt}, WRONG OTP)", enroll_response.json())
                if attempt < MAX_OTP_ATTEMPTS:
                    print_failure(f"{signature['message']} ({MAX_OTP_ATTEMPTS - attempt} attempt(s) remaining -- try again.)")
                    continue
                print_failure(f"{signature['message']} All {MAX_OTP_ATTEMPTS} attempts exhausted -- giving up.")
                return {"txn_id": txn_id, "response": None, "mobile_number": mobile_number}

            # Unrecognized failure shape -- full raw dump, not retried (we
            # don't yet know this is a user-input problem).
            report_failure(enroll_response, "Enrollment failed")
            return {"txn_id": txn_id, "response": None, "mobile_number": mobile_number}

        enroll_body = enroll_response.json()
        _print_outcome(enroll_body)
        return {"txn_id": txn_id, "response": enroll_body, "mobile_number": mobile_number}

    # Unreachable -- the loop above always returns. Kept only as a
    # defensive fallback in case that ever stops being true.
    return {"txn_id": txn_id, "response": None, "mobile_number": mobile_number}


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
