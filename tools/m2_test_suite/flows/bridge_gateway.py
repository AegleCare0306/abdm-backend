"""
Flows 1-4 -- Bridge/Gateway admin APIs. All four are synchronous
(direct request/response, no callback) -- no server precheck needed.
"""

from server import config
from server.auth import update_bridge_url, find_bridge_service_by_id, find_services_by_bridge_id
from server.facility import register_bridge_service
from server.utils import print_api_response

from tools.m2_test_suite.common import (
    prompt,
    print_header,
    print_info,
    print_success,
    print_failure,
    print_response_body,
    select_facility,
)


def run_update_bridge_url():
    print_header("Flow 1: Update Bridge URL")

    callback_url = prompt(f"Callback URL [default: {config.CALLBACK_URL}]") or config.CALLBACK_URL

    print_info(f"Updating bridge URL to: {callback_url}")
    response = update_bridge_url(callback_url)

    if response.status_code == 202:
        print_success(f"Bridge URL updated (status {response.status_code}).")
    else:
        print_failure(f"Unexpected status {response.status_code} (expected 202).")
        print_api_response(response)

    return {"callback_url": callback_url, "status_code": response.status_code}


def run_register_bridge_service():
    print_header("Flow 2: Registration of Bridge Service (HIP/HIU)")

    facility = select_facility()
    facility_id = facility["hip_id"]
    facility_name = facility["organization_name"]

    print_info("hipName constraints (per M2 doc): max 15 characters, no special characters, must be unique per bridge for this facility.")
    hip_name = prompt("hipName")

    service_type = prompt("Service type (HIP/HIU) [default: HIP]") or "HIP"

    active_input = prompt("Active? (y/n) [default: y]") or "y"
    active = active_input.strip().lower() in ("y", "yes", "true", "1")

    bridge_id = prompt(f"Bridge ID [default: {config.CLIENT_ID}]") or config.CLIENT_ID

    print_info("Calling register_bridge_service()...")
    response = register_bridge_service(
        facility_id=facility_id,
        facility_name=facility_name,
        hip_name=hip_name,
        service_type=service_type,
        active=active,
        bridge_id=bridge_id,
    )

    print_info(f"Status: {response.status_code}")

    # This endpoint's failure shape was unconfirmed until a real test run
    # (2026-08-04): ABDM can return HTTP 200 with a body that is itself an
    # error -- a list containing {"error": {"code": ..., "message": ...}}
    # (real example: code 2500, "Provided facility name is not matched
    # with registered name"). A plain status-code check would have called
    # that a success, so this now inspects the body too.
    try:
        body = response.json()
    except ValueError:
        body = None

    is_error_body = isinstance(body, list) and body and isinstance(body[0], dict) and "error" in body[0]

    if response.status_code == 200 and not is_error_body:
        print_success("Registration succeeded.")
        print_response_body(response)
    else:
        print_failure(f"Registration failed (status {response.status_code}).")
        print_api_response(response)

    return {"facility_id": facility_id, "hip_name": hip_name, "status_code": response.status_code}


def run_find_bridge_service_by_id():
    print_header("Flow 3: Find Bridge Service By Service ID")

    print_info("service_id is an ABDM-assigned value from a prior registration -- e.g. the hipName used in Registration of Bridge Service. Not something found in the CSVs.")
    service_id = prompt("Service ID")

    response = find_bridge_service_by_id(service_id)

    print_info(f"Status: {response.status_code}")

    if response.status_code == 200:
        print_success("Service found.")
        print_response_body(response)
    else:
        print_failure(f"Unexpected status {response.status_code} (expected 200).")
        print_api_response(response)

    return {"service_id": service_id, "status_code": response.status_code}


def run_find_services_by_bridge_id():
    print_header("Flow 4: Find Services By Bridge ID")

    print_info("No input needed -- ABDM resolves the bridge from the Authorization token itself. (Corrected 2026-08-04: this used to prompt for a bridgeId and append it to the URL, based on a stale Postman example response -- the collection's actual live request template has no bridgeId anywhere.)")

    response = find_services_by_bridge_id()

    print_info(f"Status: {response.status_code}")

    if response.status_code == 200:
        print_success("Bridge and services found.")
        print_response_body(response)
    else:
        print_failure(f"Unexpected status {response.status_code} (expected 200).")
        print_api_response(response)

    return {"status_code": response.status_code}
