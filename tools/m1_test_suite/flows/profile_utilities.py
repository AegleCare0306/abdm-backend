"""
Flow 12 -- Profile Utilities (sub-menu, chains off a login).

Confirmed scope decision: logs in via Flow 5 SPECIFICALLY
(flows.login_abha_number.run_abha_registered_mobile -- "Login using ABHA
Number (OTP - ABHA Registered Mobile Number)"), not a menu of login
choices, then offers a nested sub-menu (same numbered-prompt pattern as
the main CLI menu in cli.py) of the 4 profile-related APIs that all just
need the resulting X-Token:
  1. Linking & Updating E-Mail
  2. Download ABHA Card
  3. Get User QR Code
  4. Retrieve ABHA User Profile

BUG FIX NOTE: server.abha.get_profile()/get_qr_code()/get_abha_card() had
a pre-existing bug -- they called get_resource(get_gateway_token(), x_token, ...),
passing the gateway token as the x_token argument and the real x_token as
the action argument (get_resource already fetches its own gateway token
internally and never needed one passed in). This made every call these
three wrappers ever made build a broken URL/X-Token header. Confirmed via
a repo-wide grep that nothing else called these three functions, so no
existing behavior depended on the bug. Fixed directly in server/abha.py
(also added the `action` parameter these wrappers now accept, matching
this flow's calls below) -- see that file's diff.
"""

from datetime import datetime
from pathlib import Path

from server.abha import request_email_verification_link, get_abha_card, get_qr_code, get_profile

from tools.m1_test_suite.flows import login_abha_number
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

_DOWNLOADS_DIR = Path(__file__).resolve().parents[1] / "downloads"

# Best-effort only -- the doc says "image/PDF" without pinning down which
# is which for card vs QR code. Falls back to .bin when the Content-Type
# isn't one of these, so nothing is ever lost, just less nicely named.
_EXTENSION_BY_CONTENT_TYPE = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}


def run():
    print_header("Flow 12: Profile Utilities")

    print_info("Logging in via Flow 5 (Login using ABHA Number, OTP - ABHA Registered Mobile Number)...")
    login_result = login_abha_number.run_abha_registered_mobile()

    x_token = login_result.get("x_token")
    if x_token is None:
        print_failure("Login failed -- nothing to do.")
        return {"x_token": None, "performed": []}

    sub_flows = [
        {"name": "Linking & Updating E-Mail", "handler": _link_email},
        {"name": "Download ABHA Card", "handler": _download_abha_card},
        {"name": "Get User QR Code", "handler": _download_qr_code},
        {"name": "Retrieve ABHA User Profile", "handler": _retrieve_profile},
    ]

    performed = []

    while True:
        print("\n" + "-" * 60)
        print("Profile Utilities -- choose an action:")
        for i, sub in enumerate(sub_flows, start=1):
            print(f"  {i}. {sub['name']}")
        print("  0. Back to main menu")

        choice = prompt("Choice")

        if choice in ("0", "q", "quit", "exit"):
            break

        if not choice.isdigit() or not (1 <= int(choice) <= len(sub_flows)):
            print_info(f"Invalid choice: {choice!r}")
            continue

        sub = sub_flows[int(choice) - 1]

        try:
            sub["handler"](x_token)
            performed.append(sub["name"])
        except Exception as exc:
            print_failure(f"{sub['name']} raised an unexpected error: {type(exc).__name__}: {exc}")

    return {"x_token": x_token, "performed": performed}


def _link_email(x_token):
    email = prompt("Email address to link")

    print_info("Requesting email verification link...")
    response = request_email_verification_link(
        x_token=x_token,
        action="profile/account",
        scope=["abha-profile", "email-link-verify"],
        login_hint="email",
        login_id=encrypt(email),
        otp_system="abdm",
    )

    if response.status_code != 200:
        report_failure(response, "Email verification link request failed")
        return

    # MALFORMED-BODY GUARD (tracker case M1-7, extended here for
    # consistency -- see login_search.py's matching guard for the full
    # rationale). This one was already caught by run()'s own per-sub-flow
    # try/except (a generic "raised an unexpected error" message), so not
    # a silent crash before this fix -- but this gives a clearer, specific
    # message instead of relying on that generic catch-all.
    try:
        body = response.json()
    except ValueError as exc:
        print_failure(f"Email verification link request returned a 200 status but the response body wasn't valid JSON ({exc}).")
        return
    print_success(body.get("message", "Verification link sent."))
    print_info("No further completion step for this one -- per the doc, the user finishes by clicking the link sent to their inbox; no follow-up API call exists in this codebase.")
    log_response("request_email_verification_link response", body)


def _save_binary(response, label):
    _DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
    extension = _EXTENSION_BY_CONTENT_TYPE.get(content_type, ".bin")
    filename = f"{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{extension}"
    filepath = _DOWNLOADS_DIR / filename
    filepath.write_bytes(response.content)
    return filepath


def _download_abha_card(x_token):
    print_info("Downloading ABHA Card...")
    response = get_abha_card(x_token, action="profile/account")

    if response.status_code != 200:
        report_failure(response, "ABHA Card download failed")
        return

    filepath = _save_binary(response, "abha_card")
    print_success(f"ABHA Card saved to {filepath}")


def _download_qr_code(x_token):
    print_info("Downloading QR Code...")
    response = get_qr_code(x_token, action="profile/account")

    if response.status_code != 200:
        report_failure(response, "QR Code download failed")
        return

    filepath = _save_binary(response, "qr_code")
    print_success(f"QR Code saved to {filepath}")


def _retrieve_profile(x_token):
    print_info("Retrieving ABHA user profile...")
    response = get_profile(x_token, action="profile/account")

    if response.status_code != 200:
        report_failure(response, "Profile retrieval failed")
        return

    # MALFORMED-BODY GUARD (tracker case M1-7, extended here -- see
    # _link_email()'s matching guard above).
    try:
        body = response.json()
    except ValueError as exc:
        print_failure(f"Profile retrieval returned a 200 status but the response body wasn't valid JSON ({exc}).")
        return

    name = first_present(body, "name", "fullName")
    abha_number = first_present(body, "ABHANumber", "healthIdNumber", "abhaNumber")
    abha_address = first_present(body, "preferredAbhaAddress", "phrAddress", "abhaAddress")
    mobile_verified = body.get("mobileVerified")
    email_verified = body.get("emailVerified")
    kyc_verified = first_present(body, "kycVerified", "KycVerified")

    print_success("Profile retrieved.")
    print_info(f"Name            : {name}")
    print_info(f"ABHA Number     : {abha_number}")
    print_info(f"ABHA Address    : {abha_address}")
    print_info(f"Mobile Verified : {mobile_verified}")
    print_info(f"Email Verified  : {email_verified}")
    print_info(f"KYC Verified    : {kyc_verified}")

    # Deliberately NOT dumped to console (could include a base64 photo) --
    # same convention as every other flow, full body goes to the log file.
    log_response("get_profile response", body)
