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

from server.hiu_health_information import (
    initiate_health_information_request,
    validate_date_range_against_consent,
    DateRangeValidationError,
)
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

    # Loop locally until the entered range validates against the consent's
    # own approved dateRange -- checked with the exact same
    # validate_date_range_against_consent() that initiate_health_information_request()
    # itself calls, so there's no separate/duplicated notion of "valid"
    # between the CLI's own check and the outbound call's. This avoids
    # ever spending a live ABDM round trip on a range we can already
    # rule out ourselves (confirmed live, 2026-08-11: ABDM rejects an
    # out-of-range request asynchronously as ABDM-1063 "Date Range given
    # is invalid" -- slow, and simply unnecessary to hit at all here). A
    # real UI would express this same constraint as a date picker bounded
    # to consent_date_range's own from/to rather than a re-prompt loop.
    if consent_date_range.get("from") and consent_date_range.get("to"):
        print_info(f"This consent's approved date range: {consent_date_range['from']} to {consent_date_range['to']}")

    while True:
        date_range_from = prompt_with_default("Date range from (ISO 8601)", consent_date_range.get("from") or _iso(now))
        date_range_to = prompt_with_default("Date range to (ISO 8601)", consent_date_range.get("to") or _iso(now))

        try:
            validate_date_range_against_consent(consent_id, date_range_from, date_range_to)
            break
        except DateRangeValidationError as exc:
            print_failure(str(exc))
            print_info("Enter a date range within the consent's approved window shown above.")

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

    # This call's own REQUEST-ID -- see initiate_health_information_request()'s
    # docstring (Returns). Used below to pick THIS call's own on-request
    # callback out of a shared capture file that may also contain other
    # concurrent Block 2 requests' callbacks.
    our_request_id = getattr(response, "aegle_request_id", None)

    def _is_our_on_request(entry):
        # ABDM echoes our original REQUEST-ID back as response.requestId
        # on the on-request callback, whether it's a success (hiRequest
        # populated) or a rejection (hiRequest: null, error populated) --
        # confirmed against both shapes in storage/api_capture/m3_*.jsonl,
        # 2026-08-11. Falls back to "match anything of this label" only
        # if our_request_id itself is somehow unavailable, so this never
        # makes matching MORE restrictive than the old behaviour was.
        if our_request_id is None:
            return True
        body = entry.get("request_body") or {}
        return (body.get("response") or {}).get("requestId") == our_request_id

    print_info("Waiting for ABDM's on-request ack (transactionId)...")
    on_request_entry = wait_for_callback(
        "health_information_hiu_on_request",
        since=start_time,
        match_fn=_is_our_on_request,
    )

    if on_request_entry is None:
        print_failure("Timed out waiting for the on-request callback.")
        print_info("Is the server running? Is the ngrok tunnel up? Did ABDM actually receive the original call?")
        print_info("(The on-request callback path itself is confirmed -- M3 spec doc section 5.3.2 -- so a timeout "
                    "here points at connectivity/tunnel issues, not a wrong listening path. If another Health "
                    "Information Request is running concurrently, also check storage/api_capture/m3_*.jsonl "
                    "directly for a same-label entry that arrived but wasn't matched to THIS call.)")
        return {"consent_id": consent_id}

    log_response("on-request callback", on_request_entry)

    on_request_body = on_request_entry.get("request_body") or {}
    hi_request = on_request_body.get("hiRequest")

    if hi_request is None:
        # ABDM rejected the request outright (hiRequest: null, error
        # populated instead) -- e.g. ABDM-1063 "Date Range given is
        # invalid". Confirmed live, 2026-08-11: the old code here did
        # `.get("hiRequest", {}).get("transactionId")`, which only falls
        # back to {} when the KEY is missing, not when it's present and
        # explicitly null -- so this exact rejection shape crashed the
        # CLI with an unhandled AttributeError instead of failing
        # gracefully. Fixed by checking for this case explicitly first.
        error = on_request_body.get("error") or {}
        print_failure(f"ABDM rejected this request: {error.get('message', 'no message')} ({error.get('code', 'no code')})")
        print_info("This should have been caught by validate_date_range_against_consent() before this call was "
                    "ever made -- if you're seeing this, either an out-of-band caller bypassed that check, or "
                    "this CLI process is running stale code from before that check existed (restart it after any "
                    "code change -- edits to already-imported modules do not hot-reload).")
        return {"consent_id": consent_id}

    transaction_id = hi_request.get("transactionId")
    print_success(f"transactionId received: {transaction_id}")

    # CHANGED 2026-08-12: a transfer covering more than one care context
    # now arrives as MULTIPLE separate pushes (one per care context, each
    # its own page) instead of a single push carrying every entry -- see
    # health_information_request_service.py's _push_and_notify() and
    # health_information_hiu_push_service.py's own docstrings for why
    # (fixes an AES-GCM key/IV reuse issue on the sender side). The
    # server only sends the final "transfer complete" notify once it's
    # received the LAST page, so this now specifically waits for that
    # last push rather than stopping at the first one it sees -- waiting
    # for just the first push (the old behavior) would report a partial,
    # possibly-empty result for any multi-care-context transfer.
    def _is_our_last_push(entry):
        if transaction_id is None:
            return True
        body = entry.get("request_body") or {}
        if body.get("transactionId") != transaction_id:
            return False
        page_number = body.get("pageNumber")
        page_count = body.get("pageCount")
        if page_count is None or page_number is None:
            return True
        return page_number >= page_count - 1

    print_info("Waiting for the HIP to push encrypted records directly to our dataPushUrl "
                "(may arrive as multiple pages, one per care context)...")
    push_entry = wait_for_callback(
        "health_information_hiu_push",
        since=start_time,
        match_fn=_is_our_last_push,
    )

    if push_entry is None:
        print_failure("Timed out waiting for the data push.")
        print_info("Is the HIP's own server actually running and able to reach our dataPushUrl?")
        print_info("(If another Health Information Request is running concurrently, also check "
                    "storage/api_capture/m3_*.jsonl directly for a push entry with this transactionId that "
                    "arrived but wasn't matched here. Also check for EARLIER pages of this same transfer that "
                    "arrived but never got a final page -- that would mean the HIP sent fewer pages than its "
                    "own pageCount promised.)")
        return {"consent_id": consent_id, "transaction_id": transaction_id}

    log_response("data push callback (last page)", push_entry)

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
