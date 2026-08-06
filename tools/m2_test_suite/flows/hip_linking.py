"""
Flows 5-7 -- HIP-Initiated Linking APIs. All three are async (202
Accepted + a later callback) and require the local server (with the
ngrok tunnel active) to be reachable before firing the outbound call.

Get All Patient Links (M2 doc §4.3.5) is deliberately NOT implemented
here -- per the doc's own text it's a PHR-app-facing query, not a HIP
concern, so it's out of scope for this codebase (which implements HIP,
not PHR). Removed 2026-08-04; the original implementation (server-side
function, this flow, and the CLI menu entry) is preserved in git history
if PHR scope is ever picked up.
"""

from datetime import datetime, timezone

from server.hip_linking import (
    generate_link_token,
    link_care_context,
    notify_care_context_update,
    send_sms_notification,
    ReusedLinkToken,
    is_duplicate_link_error,
)
from server.callbacks.repository.patient_link_token_repository import get_patient_link_token
from server.callbacks.transformers.patient_transformer import build_patient_payload
from server.utils import print_api_response

from tools.m2_test_suite.common import (
    prompt,
    print_header,
    print_info,
    print_success,
    print_failure,
    log_response,
    select_facility,
    select_patient,
    select_care_contexts,
    check_server_running,
    wait_for_callback,
)

SERVER_NOT_RUNNING_MESSAGE = "Start the server first: `uvicorn server.main:app --reload` (with the ngrok tunnel active)."


def _print_link_care_context_failure(response):
    """
    Shared by both Flow 5 paths (new-token and reused-token) for a
    non-202 link_care_context() response. Distinguishes ABDM's real,
    confirmed "this care context is already linked" response
    (is_duplicate_link_error(), 2026-08-05) from a genuine failure --
    printing it as informational rather than the scary ABDM API ERROR
    dump, since re-submitting an already-linked care context isn't
    actually a problem, just redundant.
    """
    try:
        body = response.json()
    except ValueError:
        body = response.text

    if is_duplicate_link_error(body):
        print_info(f"Already linked (ABDM: \"Duplicate HIP link request\") -- nothing to do, not a real failure.")
        return True

    print_failure(f"Unexpected status {response.status_code} (expected 202).")
    print_api_response(response)
    return False


def _link_care_context_with_reused_token(reused, requested_hip_id, patient, start_time, selected_records):
    """
    Reuse path for Flow 5 -- generate_link_token() returned a
    ReusedLinkToken instead of firing a real generate-token call (a
    saved token already existed for this patient). Visibly different
    from the new-token path: no 202 wait, no on-generate-token wait --
    this calls link_care_context() directly with the reused token, for
    real, then still waits for the on_carecontext callback (that part of
    the chain has no server-side auto-trigger here, since there was no
    generate-token call for the server to react to).

    CONFIRMED REAL BUG (2026-08-06), now fixed: this used to call
    select_care_contexts() again here, re-prompting the user for the
    exact same choice they'd already made in run_link_token_and_care_context()
    right before generate_link_token() was called -- that earlier
    selection is only consumed by the NEW-token path (threaded into the
    pending session for the server to read back later), so the reuse
    path was silently discarding it and asking a second time. Takes the
    already-made selected_records directly now; no second prompt.
    """
    print_success(
        f"Reusing an existing saved link token for {reused.abha_address} "
        f"(received {reused.received_at}) -- no generate-token call made, nothing to wait for there."
    )

    # reused.hip_id is guaranteed to equal requested_hip_id as of
    # 2026-08-05 -- generate_link_token() only reuses a token saved for
    # the EXACT hip_id requested (see patient_link_token_repository.py).
    # A mismatch here used to be possible and was silently worked around
    # by using the token's own hip_id instead of the one actually
    # selected -- that was the real bug; this parameter is kept for the
    # caller's convenience/logging, not because a mismatch can occur.
    hip_id = reused.hip_id

    print_info("Calling link_care_context() directly with the reused token...")
    patient_records = build_patient_payload(selected_records)

    response = link_care_context(
        hip_id=hip_id,
        abha_address=reused.abha_address,
        link_token=reused.link_token,
        patient_records=patient_records,
        abha_number=patient["abha_number"],
    )

    print_info(f"Status: {response.status_code}")

    if response.status_code != 202:
        _print_link_care_context_failure(response)
        return {"hip_id": hip_id, "abha_address": reused.abha_address, "reused_token": True, "status_code": response.status_code}

    print_success("Care context link accepted (202).")

    print_info("Waiting for ABDM's on_carecontext confirmation...")
    care_context_entry = wait_for_callback("care_context_link", since=start_time)

    if care_context_entry is None:
        print_failure("Timed out waiting for the on_carecontext callback.")
        print_info("Is the server running? Is the ngrok tunnel up? Did ABDM actually receive the original call?")
        return {"hip_id": hip_id, "abha_address": reused.abha_address, "reused_token": True}

    care_context_body = care_context_entry.get("request_body", {})

    if care_context_body.get("error"):
        print_failure(f"Care context link failed: {care_context_body.get('error')}")
    else:
        print_success(f"Care context link result: {care_context_body.get('status')}")

    log_response("on_carecontext callback", care_context_entry)

    return {
        "hip_id": hip_id,
        "abha_address": reused.abha_address,
        "reused_token": True,
        "care_context_result": care_context_body,
    }


def run_link_token_and_care_context():
    print_header("Flow 5: Link Token Generation + Linking Care Context (async, chained)")

    facility = select_facility()
    hip_id = facility["hip_id"]

    patient = select_patient()

    if not check_server_running():
        print_failure(SERVER_NOT_RUNNING_MESSAGE)
        return None

    # Chosen up front, before the generate-token call, because once ABDM's
    # on-generate-token callback arrives, link_care_context() is
    # auto-triggered server-side (no CLI prompt available at that point).
    # The selection is threaded through generate_link_token() into the
    # pending-session file so the server process can honor it later.
    print_info("Choose which care context records to link once the token is confirmed:")
    selected_records = select_care_contexts(patient["abha_address"], hip_id=hip_id, multi_select=True)
    selected_refs = [r["care_context_reference"] for r in selected_records] if selected_records else None

    start_time = datetime.now(timezone.utc)

    print_info("Calling generate_link_token()...")
    result = generate_link_token(
        hip_id=hip_id,
        abha_address=patient["abha_address"],
        name=patient["name"],
        gender=patient["gender"],
        year_of_birth=patient["year_of_birth"],
        abha_number=patient["abha_number"],
        selected_care_context_references=selected_refs,
    )

    if isinstance(result, ReusedLinkToken):
        return _link_care_context_with_reused_token(result, hip_id, patient, start_time, selected_records)

    response = result

    print_info(f"Status: {response.status_code}")

    if response.status_code != 202:
        print_failure(f"Unexpected status {response.status_code} (expected 202).")
        print_api_response(response)
        return {"hip_id": hip_id, "abha_address": patient["abha_address"], "status_code": response.status_code}

    print_success("Link token request accepted (202).")

    print_info("Waiting for ABDM's on-generate-token callback...")
    generate_token_entry = wait_for_callback("generate_token", since=start_time)

    if generate_token_entry is None:
        print_failure("Timed out waiting for the on-generate-token callback.")
        print_info("Is the server running? Is the ngrok tunnel up? Did ABDM actually receive the original call?")
        return {"hip_id": hip_id, "abha_address": patient["abha_address"]}

    link_token = generate_token_entry.get("request_body", {}).get("linkToken")

    if link_token:
        print_success(f"linkToken received (length {len(link_token)}).")
    else:
        print_failure("Callback arrived but linkToken is missing/empty.")

    log_response("on-generate-token callback", generate_token_entry)

    print_info("Real server has now auto-triggered Linking Care Context -- waiting for on_carecontext...")
    care_context_entry = wait_for_callback("care_context_link", since=start_time)

    if care_context_entry is None:
        print_failure("Timed out waiting for the on_carecontext callback.")
        print_info("Is the server running? Is the ngrok tunnel up? Did ABDM actually receive the original call?")
        return {"hip_id": hip_id, "abha_address": patient["abha_address"], "link_token_present": bool(link_token)}

    care_context_body = care_context_entry.get("request_body", {})

    if care_context_body.get("error"):
        print_failure(f"Care context link failed: {care_context_body.get('error')}")
    else:
        print_success(f"Care context link result: {care_context_body.get('status')}")

    log_response("on_carecontext callback", care_context_entry)

    return {
        "hip_id": hip_id,
        "abha_address": patient["abha_address"],
        "link_token_present": bool(link_token),
        "care_context_result": care_context_body,
    }


def run_notify_care_context_update():
    print_header("Flow 6: Notify Care Context Update (async)")

    facility = select_facility()
    hip_id = facility["hip_id"]

    # This call doesn't send gender/date_of_birth -- show every patient,
    # including the real ABHA-linked ones missing that data in the CSV.
    patient = select_patient(require_demographics=False)

    care_context = select_care_contexts(patient["abha_address"], hip_id=hip_id, single=True)

    if care_context is None:
        return None

    saved_token = get_patient_link_token(patient["abha_address"], hip_id)

    if saved_token is not None:
        print_success(f"Using a saved link token for {patient['abha_address']} (received {saved_token['received_at']}) -- no manual paste needed.")
        link_token = saved_token["link_token"]
    else:
        print_info("No saved link token found for this patient -- run Link Token Generation first, or paste one manually below.")
        link_token = prompt("Link token")

    if not check_server_running():
        print_failure(SERVER_NOT_RUNNING_MESSAGE)
        return None

    start_time = datetime.now(timezone.utc)

    print_info("Calling notify_care_context_update()...")
    response = notify_care_context_update(
        hip_id=hip_id,
        abha_address=patient["abha_address"],
        patient_reference=care_context["patient_reference"],
        care_context_reference=care_context["care_context_reference"],
        hi_types=[care_context["hi_type"]],
        link_token=link_token,
    )

    print_info(f"Status: {response.status_code}")

    if response.status_code != 202:
        print_failure(f"Unexpected status {response.status_code} (expected 202).")
        print_api_response(response)
        return {"hip_id": hip_id, "abha_address": patient["abha_address"], "status_code": response.status_code}

    print_success("Notify accepted (202).")

    print_info("Waiting for ABDM's on-notify callback...")
    entry = wait_for_callback("care_context_notify", since=start_time)

    if entry is None:
        print_failure("Timed out waiting for the on-notify callback.")
        print_info("Is the server running? Is the ngrok tunnel up? Did ABDM actually receive the original call?")
        return {"hip_id": hip_id, "abha_address": patient["abha_address"]}

    log_response("links/context/on-notify callback", entry)
    print_success("Callback received.")
    print_info(f"Body: {entry.get('request_body')}")

    return {"hip_id": hip_id, "abha_address": patient["abha_address"], "callback": entry.get("request_body")}


def run_send_sms_notification():
    print_header("Flow 7: SMS Notification (async)")

    facility = select_facility()
    hip_id = facility["hip_id"]
    hip_name = facility["organization_name"]

    # This call only needs a phone number -- show every patient, including
    # the real ABHA-linked ones missing gender/date_of_birth in the CSV.
    patient = select_patient(require_demographics=False)

    phone_no = prompt(f"Phone number [default: {patient['mobile']}]") or patient["mobile"]

    if not check_server_running():
        print_failure(SERVER_NOT_RUNNING_MESSAGE)
        return None

    start_time = datetime.now(timezone.utc)

    print_info("Calling send_sms_notification()...")
    response = send_sms_notification(hip_id=hip_id, hip_name=hip_name, phone_no=phone_no)

    print_info(f"Status: {response.status_code}")

    if response.status_code != 202:
        print_failure(f"Unexpected status {response.status_code} (expected 202).")
        print_api_response(response)
        return {"hip_id": hip_id, "phone_no": phone_no, "status_code": response.status_code}

    print_success("SMS notification request accepted (202).")

    print_info("Waiting for ABDM's sms/on-notify callback...")
    entry = wait_for_callback("sms_notify", since=start_time)

    if entry is None:
        print_failure("Timed out waiting for the sms/on-notify callback.")
        print_info("Is the server running? Is the ngrok tunnel up? Did ABDM actually receive the original call?")
        return {"hip_id": hip_id, "phone_no": phone_no}

    log_response("patients/sms/on-notify callback", entry)
    print_success("Callback received.")
    print_info(f"Body: {entry.get('request_body')}")

    return {"hip_id": hip_id, "phone_no": phone_no, "callback": entry.get("request_body")}
