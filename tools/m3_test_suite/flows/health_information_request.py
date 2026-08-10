"""
Flow 2 -- Health Information Request (M3 Block 2). Lets the user pick a
GRANTED consent, fires the outbound POST
.../data-flow/v3/health-information/request call, then polls for the
on-request ack and the eventual data push + notify outcome -- the same
way Block 1's own flow polls for its callbacks (see
tools/m3_test_suite/common.py's wait_for_callback(), a scoped-to-m3 port
of tools/m2_test_suite/common.py's same-named helper).
"""

from datetime import datetime, timezone

from server.hiu_health_information import initiate_health_information_request
from server.callbacks.repository.hiu_health_information_repository import get_hiu_health_information
from server.utils import print_api_response

from tools.m3_test_suite.common import (
    prompt_with_default,
    print_header,
    print_info,
    print_success,
    print_failure,
    log_response,
    select_granted_consent,
    check_server_running,
    wait_for_callback,
)

SERVER_NOT_RUNNING_MESSAGE = (
    "Start the server first: `uvicorn server.main:app --reload` (with the ngrok tunnel active) -- "
    "the on-request/push callbacks need it reachable to complete Block 2."
)


def _iso(dt):
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def run_initiate_health_information_request():
    print_header("Flow 2: Health Information Request (async, Block 2)")

    selected = select_granted_consent()
    if selected is None:
        return None

    consent_id = selected["consent_id"]
    consent_detail = selected["consent_detail"]
    hiu_id = (consent_detail.get("hiu") or {}).get("id")
    hip_id = (consent_detail.get("hip") or {}).get("id")
    consent_date_range = (consent_detail.get("permission") or {}).get("dateRange") or {}

    now = datetime.now(timezone.utc)
    date_range_from = prompt_with_default("Date range from (ISO 8601)", consent_date_range.get("from") or _iso(now))
    date_range_to = prompt_with_default("Date range to (ISO 8601)", consent_date_range.get("to") or _iso(now))

    if not check_server_running():
        print_failure(SERVER_NOT_RUNNING_MESSAGE)
        return None

    start_time = datetime.now(timezone.utc)

    print_info("Calling initiate_health_information_request()...")
    response = initiate_health_information_request(
        hiu_id=hiu_id,
        consent_id=consent_id,
        hip_id=hip_id,
        date_range_from=date_range_from,
        date_range_to=date_range_to,
    )

    print_info(f"Status: {response.status_code}")

    if response.status_code != 202:
        print_failure(f"Unexpected status {response.status_code} (expected 202).")
        print_api_response(response)
        return {"consent_id": consent_id, "status_code": response.status_code}

    print_success("Health information request accepted (202).")

    print_info("Waiting for ABDM's on-request ack (transactionId)...")
    on_request_entry = wait_for_callback("health_information_hiu_on_request", since=start_time)

    if on_request_entry is None:
        print_failure("Timed out waiting for the on-request callback.")
        print_info("Is the server running? Is the ngrok tunnel up? Did ABDM actually receive the original call?")
        print_info("(The on-request callback path itself is confirmed -- M3 spec doc section 5.3.2 -- so a timeout "
                    "here points at connectivity/tunnel issues, not a wrong listening path.)")
        return {"consent_id": consent_id}

    transaction_id = (on_request_entry.get("request_body") or {}).get("hiRequest", {}).get("transactionId")
    print_success(f"transactionId received: {transaction_id}")
    log_response("on-request callback", on_request_entry)

    print_info("Waiting for the HIP to push encrypted records directly to our dataPushUrl...")
    push_entry = wait_for_callback("health_information_hiu_push", since=start_time)

    if push_entry is None:
        print_failure("Timed out waiting for the data push.")
        print_info("Is the HIP's own server actually running and able to reach our dataPushUrl?")
        return {"consent_id": consent_id, "transaction_id": transaction_id}

    log_response("data push callback", push_entry)

    stored = get_hiu_health_information(transaction_id) if transaction_id else None

    if stored is None:
        print_failure("Data push arrived but nothing was stored -- check the server logs for a processing error.")
        return {"consent_id": consent_id, "transaction_id": transaction_id}

    care_contexts = stored.get("care_contexts") or {}
    # "OK", not "DELIVERED" -- the HIU's own hiStatus vocabulary, per the
    # M3 spec doc's section 5.3.3 (Notify); "DELIVERED" is the HIP's
    # vocabulary, used in M2's code, not ours.
    delivered = [ref for ref, result in care_contexts.items() if result.get("hi_status") == "OK"]
    errored = [ref for ref, result in care_contexts.items() if result.get("hi_status") != "OK"]

    if delivered:
        print_success(f"{len(delivered)} care context(s) received and decrypted successfully: {', '.join(delivered)}")
    if errored:
        print_failure(f"{len(errored)} care context(s) failed: {', '.join(errored)}")
        for ref in errored:
            print_info(f"  {ref}: {care_contexts[ref].get('description')}")

    return {
        "consent_id": consent_id,
        "transaction_id": transaction_id,
        "delivered": delivered,
        "errored": errored,
    }
