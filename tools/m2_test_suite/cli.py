"""
M2 Test CLI -- interactive tool for testing M2 (ABDM HIP-Initiated Linking
+ Bridge/Gateway Admin) flows by hand against the real ABDM sandbox.

HOW TO RUN
----------
    python tools/m2_test_suite/cli.py

Stage 1 (this file) covers the 6 direct-call APIs: 4 Bridge/Gateway admin
flows and 2 HIP-Initiated Linking flows. A later Stage 2 will add UIL
"callback simulator" flows.

Notify Care Context Update (M2 doc §4.3.6) is deliberately not a
separate menu entry -- removed 2026-08-04. It's now auto-triggered as
step 3 of the Link Token Generation + Linking Care Context chain
(server/callbacks/services/care_context_link_service.py), so testing
it standalone here would just duplicate what that flow already
exercises for real, and running both created confusing duplicate
outbound calls for the same care context during testing.

Get All Patient Links (M2 doc §4.3.5) is deliberately not included --
per the doc's own text it's a PHR-app-facing query, out of scope for
this HIP codebase. Removed 2026-08-04, recoverable from git history if
PHR scope is ever picked up.

Some flows are async (202 Accepted + a later ABDM callback) and require
the local server to be running, with the ngrok tunnel active so ABDM can
actually reach the callback URL registered via Update Bridge URL.

ADDING A NEW FLOW (Stage 2+)
------------------------------
1. Add a new module under tools/m2_test_suite/flows/ (or a function to an
   existing one) with a run_*() function that takes no arguments, prompts
   via common.prompt()/common.select_*(), and returns a plain dict.
2. Import it below and add one entry to the FLOWS list.
That's it -- the menu, dispatch, and run loop never need to change.
"""

import sys
from pathlib import Path

# tools/m2_test_suite/cli.py -> parents[2] is the repo root. Inserted
# first, before any of this package's own modules are imported, so both
# `server.*` and `tools.m2_test_suite.*` absolute imports resolve
# regardless of how this script was invoked.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.m2_test_suite.flows import bridge_gateway, hip_linking


# ---------------------------------------------------------------------------
# Registry -- add one entry here per new flow. Nothing else in this file
# needs to change to add a flow.
# ---------------------------------------------------------------------------

FLOWS = [
    {
        "name": "Update Bridge URL",
        "description": "Register/update our callback (bridge) URL with the ABDM Gateway.",
        "handler": bridge_gateway.run_update_bridge_url,
    },
    {
        "name": "Registration of Bridge Service",
        "description": "Register our bridge as an HIP/HIU service against a facility in ABDM's Health Facility Registry.",
        "handler": bridge_gateway.run_register_bridge_service,
    },
    {
        "name": "Find Bridge Service By Service ID",
        "description": "Look up a registered bridge service by its service ID.",
        "handler": bridge_gateway.run_find_bridge_service_by_id,
    },
    {
        "name": "Find Services By Bridge ID",
        "description": "Look up all services registered under a bridge (ours by default).",
        "handler": bridge_gateway.run_find_services_by_bridge_id,
    },
    {
        "name": "Link Token Generation + Linking Care Context (async, chained)",
        "description": "(async) Requests a link token, then waits for ABDM to auto-trigger and confirm care context linking.",
        "handler": hip_linking.run_link_token_and_care_context,
    },
    {
        "name": "SMS Notification",
        "description": "(async) Ask ABDM to send an SMS notification to a patient about pending care-context links.",
        "handler": hip_linking.run_send_sms_notification,
    },
]


def print_menu():
    print("\n" + "=" * 60)
    print("M2 Test CLI -- ABDM HIP-Initiated Linking + Bridge/Gateway Admin")
    print("=" * 60)
    for i, flow in enumerate(FLOWS, start=1):
        print(f"  {i}. {flow['name']}")
        print(f"     {flow['description']}")
    print("  0. Quit")


def main():
    print("M2 Test CLI -- running against the live ABDM sandbox.")
    print("Flows marked (async) require the local server (`uvicorn server.main:app --reload`) running with the ngrok tunnel active.")

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
            print(f"\n--- {flow['name']} finished. Returned: {result} ---")
        except KeyboardInterrupt:
            print("\n\nCancelled -- returning to menu.")
        except Exception as exc:
            print(f"\n{flow['name']} raised an unexpected error: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
