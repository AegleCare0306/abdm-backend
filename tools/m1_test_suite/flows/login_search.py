"""
Flows 8 & 9 -- Search and Verify using Mobile Number / Aadhaar Registered
Mobile Number.

Confirmed against the "Search ABHA Account" doc plus the "Request OTP" /
"Verify OTP" Implementation Matrices. Both variants share an identical
Search ABHA Account prerequisite step (the doc only documents one search
API, by mobile number, used by both) -- implemented once here as
_search_and_select().

SANDBOX-CONFIRMED SCOPE ASYMMETRY: request_otp() and verify_otp() do NOT
share the same scope for this flow, unlike every other login variant in
this CLI. A live sandbox run confirmed sending the 3-element request-time
scope (the one with "search-abha") to verify_otp() returns a 400 with body
{"scope": "Invalid Scope"}; request_otp() accepts that same 3-element
scope fine (the OTP was sent successfully). So the two steps deliberately
use different scope lists:

  Flow 8 -- Search and Verify using Mobile Number:
      request_otp scope=["abha-login","search-abha","mobile-verify"]
      verify_otp  scope=["abha-login","mobile-verify"]
      otpSystem=abdm.

  Flow 9 -- Search and Verify using Aadhaar Registered Mobile Number:
      request_otp scope=["abha-login","search-abha","aadhaar-verify"]
      verify_otp  scope=["abha-login","aadhaar-verify"]
      otpSystem=aadhaar.

Both: action=profile/login, loginHint=index, and -- per the doc's explicit
instruction -- the SAME txnId returned by the Search step is carried
through to request_otp() rather than letting a new one be minted.

INDEX-ENCRYPTION JUDGMENT CALL (flagged, not silently guessed -- see also
the Stage 2 report): the loginId sent in the OTP-request step is the
selected account's `index` value -- a small positional integer within the
search results, not PII like every other loginId field (Aadhaar/mobile/
ABHA-number/ABHA-address). The documentation does not state whether this
specific loginId should be RSA-encrypted or sent plain, since it isn't
sensitive data. This implementation encrypts it (str(index) through the
same encrypt() helper as every other loginId) purely for CONSISTENCY with
every other loginId field in this codebase -- this is NOT confirmed by the
documentation. See the encrypt(str(abha_index)) call in _run() below.
"""

from server.abha import search_abha_by_mobile

from tools.m1_test_suite.common import (
    prompt,
    encrypt,
    print_header,
    print_info,
    print_failure,
    log_response,
    first_present,
    report_failure,
)
from tools.m1_test_suite.login_runner import request_login_otp, verify_login_otp

SEARCH_ACTION = "profile/account"
SEARCH_SCOPE = ["search-abha"]

LOGIN_ACTION = "profile/login"
LOGIN_HINT = "index"


def _search_and_select():
    """
    Runs the shared Search ABHA Account prerequisite: prompts for a mobile
    number, calls search_abha_by_mobile(), and returns
    (txn_id, selected_abha_index). Returns (None, None) if the search call
    itself failed, OR if it succeeded but found no accounts -- per the
    doc, an empty result is a normal "no account found" outcome, not an
    error, so it's reported via print_info() rather than report_failure().
    """
    mobile_number = prompt("Mobile number (10 digits, no spaces/dashes)")

    print_info("Searching for ABHA accounts linked to this mobile number...")
    response = search_abha_by_mobile(
        action=SEARCH_ACTION,
        scope=SEARCH_SCOPE,
        mobile=encrypt(mobile_number),
    )

    if response.status_code != 200:
        report_failure(response, "ABHA search failed")
        return None, None

    # MALFORMED-BODY GUARD (edge-case-review pass, tracker case M1-7): a
    # 200 status only means the HTTP layer succeeded -- the OLD code
    # called response.json() unguarded, so a broken/non-JSON body (an
    # HTML error page, etc.) crashed here with an uncaught ValueError.
    # cli.py's own top-level try/except would have caught it (so the CLI
    # itself wouldn't have died), but the flow aborted abruptly with a
    # raw exception message instead of this module's normal clear
    # reporting -- same fix shape as M1-5's guards in login_runner.py.
    try:
        body = response.json()
    except ValueError as exc:
        print_failure(
            f"ABHA search returned a 200 status but the response body wasn't valid "
            f"JSON ({exc}) -- treating this as a failed search rather than crashing."
        )
        log_response("search_abha_by_mobile response was not valid JSON", response.text)
        return None, None

    if not body:
        print_failure("Search returned an empty response.")
        return None, None

    # SHAPE GUARD (tracker case M1-11): the doc's own example response is
    # a list, but the author flagged uncertainty about whether ABDM ever
    # returns a single object instead when there's exactly one match.
    # The OLD code assumed `body` was always a list and indexed body[0]
    # unconditionally -- for a single dict, `dict[0]` raises KeyError,
    # not the "no accounts" outcome a real single-object response should
    # produce. Tolerantly treat a single dict as a one-element list
    # instead of crashing on it; any other non-list shape is genuinely
    # malformed, reported clearly rather than guessed at further.
    if isinstance(body, dict):
        body = [body]
    elif not isinstance(body, list):
        print_failure(
            f"ABHA search response was not a list or object (got {type(body).__name__}) "
            f"-- treating this as a failed search rather than crashing."
        )
        log_response("search_abha_by_mobile response had an unexpected top-level shape", body)
        return None, None

    result = body[0]
    if not isinstance(result, dict):
        print_failure(
            f"ABHA search response's first entry was not an object (got {type(result).__name__}) "
            f"-- treating this as a failed search rather than crashing."
        )
        log_response("search_abha_by_mobile response's first entry had an unexpected shape", body)
        return None, None

    txn_id = result.get("txnId")

    # MISSING-TXNID GUARD (tracker case M1-38): the OLD code took
    # result.get("txnId") on faith -- a missing txnId silently became
    # None, which would then be carried through as the "same txnId from
    # the search step" into request_login_otp() (per this module's own
    # docstring, sending a literal txnId: null to ABDM instead of
    # failing fast locally). Same fix shape as M1-15's enrollment guard.
    if not txn_id:
        print_failure(
            "ABHA search returned a 200/success response but no 'txnId' was found in "
            "the result -- cannot proceed without a transaction ID to carry through."
        )
        log_response("search_abha_by_mobile response (MISSING txnId)", result)
        return None, None

    abha_list = result.get("ABHA", [])

    if not abha_list:
        print_info("No ABHA account was found for this mobile number (not an error -- nothing to select).")
        return None, None

    selected = _select_abha_result(abha_list)
    return txn_id, selected.get("index")


def _select_abha_result(abha_list):
    """
    Like common.select_account(), but for the Search ABHA Account
    response's own per-entry shape (has "index", which the accounts list
    used elsewhere doesn't) -- kept local rather than forced into the
    shared helper since the shape genuinely differs and the value needed
    here (the "index" field) differs from what every other login flow
    needs (an ABHANumber).
    """
    if len(abha_list) == 1:
        print_info("Exactly one ABHA account found -- auto-selecting it.")
        selected = abha_list[0]
        log_response("selected ABHA search result", selected)
        return selected

    print_info(f"{len(abha_list)} ABHA accounts found -- choose one:")
    for i, entry in enumerate(abha_list, start=1):
        name = first_present(entry, "name")
        abha_number = first_present(entry, "ABHANumber", "healthIdNumber")
        print_info(f"  [{i}] {name}  |  ABHA Number: {abha_number}")

    while True:
        choice = prompt(f"Enter a number (1-{len(abha_list)})")
        if choice.isdigit() and 1 <= int(choice) <= len(abha_list):
            selected = abha_list[int(choice) - 1]
            log_response("selected ABHA search result", selected)
            return selected
        print_info("Invalid choice, try again.")


def _run(flow_title, request_scope, verify_scope, otp_system):
    print_header(flow_title)

    search_txn_id, abha_index = _search_and_select()
    if search_txn_id is None or abha_index is None:
        return {"x_token": None, "accounts": [], "txn_id": search_txn_id}

    # JUDGMENT CALL (see module docstring): encrypting the index loginId
    # for consistency with every other loginId field -- NOT confirmed by
    # the documentation.
    login_id = encrypt(str(abha_index))

    txn_id = request_login_otp(
        action=LOGIN_ACTION,
        scope=request_scope,
        login_hint=LOGIN_HINT,
        login_id=login_id,
        otp_system=otp_system,
        txn_id=search_txn_id,  # carry the SAME txnId from the search step through, per the doc
    )
    if txn_id is None:
        return {"x_token": None, "accounts": [], "txn_id": None}

    # verify_otp() needs the NARROWER scope here -- sending the same
    # 3-element request_scope returns a 400 "Invalid Scope" (sandbox-
    # confirmed). See module docstring.
    return verify_login_otp(action=LOGIN_ACTION, scope=verify_scope, txn_id=txn_id)


def run_mobile_verify():
    """Flow 8 -- Search and Verify using Mobile Number."""
    return _run(
        "Flow 8: Search and Verify using Mobile Number",
        request_scope=["abha-login", "search-abha", "mobile-verify"],
        verify_scope=["abha-login", "mobile-verify"],
        otp_system="abdm",
    )


def run_aadhaar_verify():
    """Flow 9 -- Search and Verify using Aadhaar Registered Mobile Number."""
    return _run(
        "Flow 9: Search and Verify using Aadhaar Registered Mobile Number",
        request_scope=["abha-login", "search-abha", "aadhaar-verify"],
        verify_scope=["abha-login", "aadhaar-verify"],
        otp_system="aadhaar",
    )
