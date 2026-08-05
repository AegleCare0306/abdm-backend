"""
Health Facility Registry (HFR) related APIs.
"""

import requests

from server.config import FACILITY_BASE_URL, CLIENT_ID
from server.utils import get_gateway_token
from server.callbacks.utils.flow_logger import log_error
from server.callbacks.utils.api_capture import record_call


def register_bridge_service(
    facility_id,
    facility_name,
    hip_name,
    service_type,
    active=True,
    bridge_id=None,
):

    """
    Register (or update) our bridge as an HIP/HIU service against a
    facility in ABDM's Health Facility Registry. This is the API-based
    path for "Registration of bridge services" (M2 doc §3.2.5, Option 2),
    as opposed to registering manually through the HFR website.

    Doc-confirmed field constraints (M2 doc §3.2.5 Parameters table):
        facility_id: Must start with "IN", 12 characters total.
        hip_name: Max 15 characters, no special characters, must be
            unique per bridge for a given facility. Convention shown in
            the doc: "<Hospital Name> <Bridge Name>" (e.g. hospital
            "XYZ" + bridge "BRIDGE TEST" -> hipName "XYZ BRIDGE").
        service_type: "HIP" or "HIU".
        active: boolean.

    Unlike every other Gateway-domain call in this codebase, this
    endpoint does NOT take REQUEST-ID/TIMESTAMP/X-CM-ID headers
    (confirmed absent by both the official doc and the saved Postman
    request) -- only Content-Type and Authorization are sent.

    CRITICAL: the success/failure response shape for this endpoint is
    UNCONFIRMED. The M2 doc's Parameters table never shows a Response
    section for this API (unlike most other APIs in the same doc), and
    the saved Postman request has zero saved example responses. No
    status code or response body shape is assumed anywhere below --
    the caller must inspect response.status_code / response body
    themselves.

    Args:
        facility_id (str): Facility ID in ABDM's HFR. Must start with
            "IN", 12 characters total.
        facility_name (str): Facility name as registered in HFR.
        hip_name (str): Name for this bridge/facility service. Max 15
            characters, no special characters, unique per bridge per
            facility.
        service_type (str): "HIP" or "HIU".
        active (bool): Whether the service is active. Default True.
        bridge_id (str, optional): Our bridge/client identity. Defaults
            to config.CLIENT_ID if not provided.
    Returns:
        requests.Response: Bridge service registration response.
    Raises:
        requests.exceptions.RequestException: If the request fails
            (network error or non-2xx response).
    """

    if bridge_id is None:
        bridge_id = CLIENT_ID

    url = f"{FACILITY_BASE_URL}/v1/bridges/MutipleHRPAddUpdateServices"

    payload = {
        "facilityId": facility_id,
        "facilityName": facility_name,
        "HRP": [
            {
                "bridgeId": bridge_id,
                "hipName": hip_name,
                "type": service_type,
                "active": active,
            }
        ],
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_gateway_token()}",
    }

    try:
        response = requests.post(
            url=url,
            json=payload,
            headers=headers,
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="register-bridge-service",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"Bridge service registration failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    record_call(
        label="register-bridge-service",
        direction="outgoing",
        method="POST",
        url=url,
        request_headers=headers,
        request_body=payload,
        response_status=response.status_code,
        response_headers=dict(response.headers),
        response_body=response_body,
    )

    return response
