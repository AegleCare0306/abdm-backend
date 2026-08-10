"""
Flow 1 -- Consent Init Request (M3 Block 1, step 1). Fires the outbound
POST .../consent/v3/request/init call and returns; the rest of Block 1
(on-init -> notify -> Consent Fetch -> on-fetch) happens asynchronously
server-side once ABDM calls back, and isn't waited on here -- there's no
synchronous result beyond ABDM's 202 Accepted for this call.
"""

from datetime import datetime, timedelta, timezone

from server.hiu_consent import initiate_consent_request
from server.utils import print_api_response

from tools.m3_test_suite.common import (
    prompt,
    prompt_with_default,
    print_header,
    print_info,
    print_success,
    print_failure,
    log_response,
    select_facility,
    select_patient,
    select_practitioner,
    select_purpose,
    select_hi_types,
    check_server_running,
)

SERVER_NOT_RUNNING_MESSAGE = (
    "Start the server first: `uvicorn server.main:app --reload` (with the ngrok tunnel active) -- "
    "the on-init/notify/on-fetch callbacks need it reachable to complete Block 1."
)


def _iso(dt):
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def run_initiate_consent_request():
    print_header("Flow 1: Consent Init Request (async, Block 1 step 1)")

    facility = select_facility()
    # HIU ID isn't a separate identity from the facility in this sandbox
    # setup (Aegle Care acts as both HIP and HIU) -- use the selected
    # facility's hip_id directly rather than asking the doctor to
    # re-confirm/retype a value we already know.
    hiu_id = facility["hip_id"]

    patient = select_patient()

    practitioner = select_practitioner(facility["hip_id"])
    requester_name = practitioner["full_name"]
    requester_identifier_value = practitioner["registration_number"]
    # NOTE: registration_system in practitioners.csv is a plain council name
    # (e.g. "Gujarat Medical Council"), not a URI -- ABDM's only confirmed
    # example (M3 doc/Postman) uses a URL ("https://www.mciindia.org").
    # Passed through as-is per team decision (2026-08-10): untested either
    # way, so a real ABDM error will tell us more than guessing a mapping
    # would. If ABDM rejects this, that's the first thing to check.
    requester_identifier_system = practitioner["registration_system"]
    # "type" labels what kind of identifier `value` is (a registration
    # number) -- not practitioner-specific, and ABDM's only confirmed
    # example always uses the same value ("REGNO1"), so this is a fixed
    # constant, not something to ask about on every run.
    requester_identifier_type = "REGNO"

    purpose = select_purpose()
    purpose_text = purpose["text"]
    purpose_code = purpose["code"]
    purpose_ref_uri = prompt_with_default("Purpose refUri", "https://www.abdm.gov.in/purpose")

    hi_types = select_hi_types()

    now = datetime.now(timezone.utc)
    date_range_from = prompt_with_default("Date range from (ISO 8601)", _iso(now - timedelta(days=365)))
    date_range_to = prompt_with_default("Date range to (ISO 8601)", _iso(now))
    data_erase_at = prompt_with_default("Data erase at (ISO 8601)", _iso(now + timedelta(days=30)))

    if not check_server_running():
        print_failure(SERVER_NOT_RUNNING_MESSAGE)
        return None

    print_info("Calling initiate_consent_request()...")
    response = initiate_consent_request(
        hiu_id=hiu_id,
        patient_abha_address=patient["abha_address"],
        requester_name=requester_name,
        requester_identifier_type=requester_identifier_type,
        requester_identifier_value=requester_identifier_value,
        requester_identifier_system=requester_identifier_system,
        purpose_text=purpose_text,
        purpose_code=purpose_code,
        purpose_ref_uri=purpose_ref_uri,
        hi_types=hi_types,
        date_range_from=date_range_from,
        date_range_to=date_range_to,
        data_erase_at=data_erase_at,
    )

    print_info(f"Status: {response.status_code}")

    if response.status_code != 202:
        print_failure(f"Unexpected status {response.status_code} (expected 202).")
        print_api_response(response)
        return {"hiu_id": hiu_id, "abha_address": patient["abha_address"], "status_code": response.status_code}

    print_success("Consent init request accepted (202).")
    print_info("The real consentRequest.id arrives via the on-init callback -- watch the running server's console (or logs/flow.log).")
    print_info("Once the patient grants consent in their PHR app, the notify callback auto-triggers Consent Fetch, then on-fetch stores the artefact -- no further action needed here.")

    log_response("consent/v3/request/init response", {"hiu_id": hiu_id, "abha_address": patient["abha_address"], "status_code": response.status_code})

    return {"hiu_id": hiu_id, "abha_address": patient["abha_address"], "status_code": response.status_code}
