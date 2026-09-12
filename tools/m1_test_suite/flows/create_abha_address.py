"""
Flow 11 -- ABHA Address Creation.

Chains off a FRESH ABHA ENROLLMENT (Flow 1), not a login -- per the
confirmed scope decision. server.abha.create_abha_address() already
exists and was built + tested in an earlier pass; this flow just wires it
into the CLI menu.
"""

from server.abha import create_abha_address

from tools.m1_test_suite.flows import enrollment
from tools.m1_test_suite.common import (
    prompt,
    print_header,
    print_info,
    print_success,
    print_failure,
    log_response,
    report_failure,
)


def run():
    print_header("Flow 11: ABHA Address Creation")

    print_info("Running a fresh ABHA enrollment first (this flow chains off one)...")
    enrollment_result = enrollment.run()

    txn_id = enrollment_result.get("txn_id")
    if not txn_id:
        print_failure("Enrollment did not complete successfully -- nothing to create an ABHA Address for.")
        return {"abha_address": None, "txn_id": None}

    desired_address = prompt('Desired ABHA Address (e.g. "yourname" -- becomes "yourname@sbx")')

    # Y/N INPUT-VALIDATION GUARD (tracker case M1-41, fixed 2026-08-17):
    # the OLD code only recognized "n"/"no" as a "no" answer and treated
    # ANYTHING else -- including "0", which a reasonable person would read
    # as a false-y "no" -- as "yes". Confirmed via a live run: typing "0"
    # at this prompt still set preferred=1, silently changing a real
    # account setting the user did not actually agree to. Now an explicit
    # allowlist for both "yes" and "no" spellings, with anything else
    # re-prompted instead of guessed at -- same allowlist-over-best-effort
    # standard already applied to Aadhaar/OTP/ABHA-Address input.
    while True:
        preferred_input = prompt("Make this the preferred ABHA Address? (Y/n)").strip().lower()
        if preferred_input in ("", "y", "yes"):
            preferred = 1
            break
        if preferred_input in ("n", "no"):
            preferred = 0
            break
        print_failure(f'"{preferred_input}" is not a valid answer -- please enter Y or n.')

    print_info(f"Creating ABHA Address '{desired_address}' (preferred={preferred})...")
    response = create_abha_address(
        action="enrollment/enrol",
        txn_id=txn_id,
        abha_address=desired_address,
        preferred=preferred,
    )

    if response.status_code != 200:
        report_failure(response, "ABHA Address creation failed")
        return {"abha_address": None, "txn_id": txn_id}

    body = response.json()
    confirmed_address = body.get("preferredAbhaAddress", desired_address)

    print_success(f"ABHA Address created: {confirmed_address}")
    log_response("create_abha_address response", body)

    return {"abha_address": confirmed_address, "txn_id": txn_id}
