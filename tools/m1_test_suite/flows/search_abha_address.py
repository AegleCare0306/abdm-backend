"""
Flow 13 -- Search ABHA by ABHA Address.

Confirmed against that doc: needs ONLY the gateway bearer token -- no
X-Token, no OTP, not chained off login or enrollment. Standalone.

NOT-FOUND SHAPE (flagged, not silently guessed): the doc doesn't document
an explicit "not found" error body for this endpoint. This treats a 200
response whose body doesn't carry a recognizable ABHA Number
(healthIdNumber/ABHANumber/abhaNumber) as a "not found" outcome and
reports it as a normal (non-error) result -- a genuine HTTP-level failure
(non-200) still goes through the standard report_failure() path. This
heuristic hasn't been live-confirmed; the full raw response is always
logged via log_response() regardless (both branches), so the real shape
is captured for review either way once this is run for real.
"""

from server.abha import search_abha_by_address

from tools.m1_test_suite.common import (
    prompt,
    print_header,
    print_info,
    print_success,
    log_response,
    first_present,
    report_failure,
)


def run():
    print_header("Flow 13: Search ABHA by ABHA Address")

    abha_address = prompt('ABHA Address to look up (e.g. "someone@sbx")')

    print_info("Searching...")
    response = search_abha_by_address(
        action="phr/web/login",
        abha_address=abha_address,
    )

    if response.status_code != 200:
        report_failure(response, "ABHA search failed")
        return {"found": False}

    body = response.json()

    health_id_number = first_present(body, "healthIdNumber", "ABHANumber", "abhaNumber")

    if not health_id_number:
        print_info(f"No ABHA account found for '{abha_address}' (not necessarily an error -- see the raw response in the log file).")
        log_response("search_abha_by_address response (not found?)", body)
        return {"found": False}

    name = first_present(body, "fullName", "name")
    status = body.get("status")
    mobile = body.get("mobile")

    print_success(f"ABHA account found for '{abha_address}'.")
    print_info(f"Name        : {name}")
    print_info(f"Status      : {status}")
    print_info(f"Mobile      : {mobile}")
    print_info(f"ABHA Number : {health_id_number}")

    log_response("search_abha_by_address response", body)

    return {"found": True, "health_id_number": health_id_number}
