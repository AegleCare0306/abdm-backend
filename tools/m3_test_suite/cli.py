"""
M3 Test CLI -- interactive tool for testing M3 (ABDM HIU Consent Request
+ Health Information Request, Blocks 1 & 2) flows by hand against the
real ABDM sandbox.

HOW TO RUN
----------
    python tools/m3_test_suite/cli.py

Covers the direct-call APIs that are actually initiated from the CLI:
Consent Init Request (Block 1) and Health Information Request (Block 2).
Everything else in both blocks -- on-init, notify (+ automatic on-notify
ack and fetch triggering), on-fetch, on-request ack, and the HIP's direct
data push -- are ABDM/HIP-initiated callbacks handled entirely
server-side (see server/callbacks/services/consent_init_on_init_service.py,
consent_hiu_notify_service.py, consent_hiu_on_fetch_service.py,
health_information_hiu_on_request_service.py,
health_information_hiu_push_service.py); there's nothing for a CLI flow
to drive beyond firing the initial call and polling for the outcome.

Requires the local server (`uvicorn server.main:app --reload`) running,
with the ngrok tunnel active, so ABDM (and, for Block 2's data push, the
HIP directly) can actually reach the callback URLs registered via Update
Bridge URL (see tools/m2_test_suite).

ADDING A NEW FLOW
------------------
1. Add a new module under tools/m3_test_suite/flows/ (or a function to an
   existing one) with a run_*() function that takes no arguments, prompts
   via common.prompt()/common.select_*(), and returns a plain dict.
2. Import it below and add one entry to the FLOWS list.
That's it -- the menu, dispatch, and run loop never need to change.
"""

import sys
from pathlib import Path

# tools/m3_test_suite/cli.py -> parents[2] is the repo root. Inserted
# first, before any of this package's own modules are imported, so both
# `server.*` and `tools.m3_test_suite.*` absolute imports resolve
# regardless of how this script was invoked.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.callbacks.utils.flow_logger import set_log_category
from tools.m3_test_suite.flows import hiu_consent, health_information_request


# ---------------------------------------------------------------------------
# Registry -- add one entry here per new flow. Nothing else in this file
# needs to change to add a flow.
# ---------------------------------------------------------------------------

FLOWS = [
    {
        "name": "Consent Init Request",
        "description": "(async) Initiates an HIU consent request against ABDM; on-init/notify/on-fetch complete server-side.",
        "handler": hiu_consent.run_initiate_consent_request,
    },
    {
        "name": "Health Information Request",
        "description": "(async) Block 2: requests data for a GRANTED consent, waits for the HIP's push, decrypts and stores it.",
        "handler": health_information_request.run_initiate_health_information_request,
    },
]


def print_menu():
    print("\n" + "=" * 60)
    print("M3 Test CLI -- ABDM HIU Consent Request + Health Information Request")
    print("=" * 60)
    for i, flow in enumerate(FLOWS, start=1):
        print(f"  {i}. {flow['name']}")
        print(f"     {flow['description']}")
    print("  0. Quit")


def main():
    # Tagged once here, before the menu loop -- see the same note in
    # tools/m1_test_suite/cli.py's main(). This process only ever does M3
    # work.
    set_log_category("m3")

    print("M3 Test CLI -- running against the live ABDM sandbox.")
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
