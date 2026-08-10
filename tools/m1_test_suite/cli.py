"""
M1 Test CLI -- interactive replacement for the old ad-hoc Jupyter notebook
used to test M1 (ABHA enrollment/login) flows by hand against the real
ABDM sandbox.

HOW TO RUN
----------
    python tools/m1_test_suite/cli.py

Picks up server.utils.get_gateway_token()'s existing token caching and
server.crypto's existing certificate caching/RSA encryption -- nothing new
is built here, this just wires the existing pieces into a menu.

ADDING A NEW FLOW (Stage 2/3)
------------------------------
1. Add a new module under tools/m1_test_suite/flows/ with a run() function
   that takes no arguments, prompts via common.prompt(), and returns a
   plain dict of whatever a later flow might chain off of.
2. Import it below and add one entry to the FLOWS list.
That's it -- the menu, dispatch, and run loop never need to change.
"""

import sys
from pathlib import Path

# tools/m1_test_suite/cli.py -> parents[2] is the repo root. Inserted first,
# before any of this package's own modules are imported, so both
# `server.*` and `tools.m1_test_suite.*` absolute imports resolve
# regardless of how this script was invoked.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.callbacks.utils.flow_logger import set_log_category
from tools.m1_test_suite.common import redact_token
from tools.m1_test_suite.flows import (
    enrollment,
    login_aadhaar,
    login_mobile,
    login_abha_number,
    login_abha_address,
    login_search,
    link_mobile,
    create_abha_address,
    profile_utilities,
    search_abha_address,
)


# ---------------------------------------------------------------------------
# Registry -- add one entry here per new flow. Nothing else in this file
# needs to change to add a flow.
# ---------------------------------------------------------------------------

FLOWS = [
    {
        "name": "ABHA Enrollment via Aadhaar",
        "description": "Create a new ABHA using an Aadhaar number + OTP.",
        "handler": enrollment.run,
    },
    {
        "name": "Login using Aadhaar Number",
        "description": "Log in to an existing ABHA using an Aadhaar number + OTP.",
        "handler": login_aadhaar.run,
    },
    {
        "name": "Login using Mobile Number",
        "description": "Log in using a mobile number + OTP, then select an ABHA account.",
        "handler": login_mobile.run,
    },
    {
        "name": "Login using ABHA Number (OTP - Aadhaar Registered Mobile Number)",
        "description": "Log in with an ABHA Number, OTP sent to the Aadhaar-registered mobile.",
        "handler": login_abha_number.run_aadhaar_registered_mobile,
    },
    {
        "name": "Login using ABHA Number (OTP - ABHA Registered Mobile Number)",
        "description": "Log in with an ABHA Number, OTP sent to the ABHA-registered mobile.",
        "handler": login_abha_number.run_abha_registered_mobile,
    },
    {
        "name": "Login using ABHA Address (OTP - ABHA Registered Mobile Number)",
        "description": "Log in with an ABHA Address, OTP sent to the ABHA-registered mobile.",
        "handler": login_abha_address.run_abha_registered_mobile,
    },
    {
        "name": "Login using ABHA Address (OTP - Aadhaar Registered Mobile Number)",
        "description": "Log in with an ABHA Address, OTP sent to the Aadhaar-registered mobile.",
        "handler": login_abha_address.run_aadhaar_registered_mobile,
    },
    {
        "name": "Search and Verify using Mobile Number",
        "description": "Search for ABHA accounts by mobile number, then log in via OTP.",
        "handler": login_search.run_mobile_verify,
    },
    {
        "name": "Search and Verify using Aadhaar Registered Mobile Number",
        "description": "Search for ABHA accounts by mobile number, then log in via Aadhaar-verified OTP.",
        "handler": login_search.run_aadhaar_verify,
    },
    {
        "name": "Linking Mobile Number",
        "description": "Runs a fresh enrollment, then links/verifies a mobile number that differs from the Aadhaar-linked one.",
        "handler": link_mobile.run,
    },
    {
        "name": "ABHA Address Creation",
        "description": "Runs a fresh enrollment, then creates a custom ABHA Address for it.",
        "handler": create_abha_address.run,
    },
    {
        "name": "Profile Utilities",
        "description": "Logs in (Flow 5), then offers Email Linking / Download ABHA Card / Get QR Code / Retrieve Profile.",
        "handler": profile_utilities.run,
    },
    {
        "name": "Search ABHA by ABHA Address",
        "description": "Looks up an ABHA account by ABHA Address -- gateway token only, no login required.",
        "handler": search_abha_address.run,
    },
]


def _redact_result(result):
    """
    A copy of a flow's return dict safe to print to the console -- with
    "x_token" redacted (see common.redact_token()). Found during a
    console-token audit: this end-of-run summary was printing the raw
    result dict, which includes the full X-Token for every login flow.
    The full value already reached the log file via that flow's own
    log_response() calls before returning here -- this is only about
    what's safe to print.
    """
    if not isinstance(result, dict) or "x_token" not in result:
        return result
    return {**result, "x_token": redact_token(result["x_token"])}


def print_menu():
    print("\n" + "=" * 60)
    print("M1 Test CLI -- ABHA Enrollment / Login")
    print("=" * 60)
    for i, flow in enumerate(FLOWS, start=1):
        print(f"  {i}. {flow['name']}")
        print(f"     {flow['description']}")
    print("  0. Quit")


def main():
    # Tagged once here, before the menu loop -- this whole process (a
    # separate OS process from the running server) only ever does M1
    # work, so every record_call()/log_*() made for the rest of its life
    # (including shared calls like a gateway token request) inherits this
    # category automatically. See server/callbacks/utils/flow_logger.py's
    # get_log_category() docstring.
    set_log_category("m1")

    print("M1 Test CLI -- running against the live ABDM sandbox.")
    print("Each flow will prompt for a real OTP sent to your Aadhaar/mobile number.")

    while True:
        print_menu()

        choice = input("\nSelect a flow: ").strip()

        if choice in ("0", "q", "quit", "exit"):
            print("Bye.")
            break

        if not choice.isdigit() or not (1 <= int(choice) <= len(FLOWS)):
            print(f"Invalid choice: {choice!r}")
            continue

        flow = FLOWS[int(choice) - 1]

        try:
            result = flow["handler"]()
            print(f"\n--- {flow['name']} finished. Returned: {_redact_result(result)} ---")
        except KeyboardInterrupt:
            print("\n\nCancelled -- returning to menu.")
        except Exception as exc:
            print(f"\n{flow['name']} raised an unexpected error: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
