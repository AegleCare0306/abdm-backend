import json
import requests

from server.config import HIECM_BASE_URL, X_CM_ID
from server.utils import generate_request_id, generate_timestamp, get_gateway_token
from server.callbacks.utils.flow_logger import log_error
from server.callbacks.utils.api_capture import record_call

# NOTE (2026-07-31): disabled during M2 documentation review. This function
# sends a discover *request* as if we were the HIU side of the exchange --
# it doesn't fit our HIP-only flow (we only ever receive/react to discover
# callbacks, never initiate them -- see server/callbacks/services/discover_service.py).
# Left over from early testing when the same app simulated both HIP and HIU
# roles. Not called anywhere in the current codebase (confirmed via repo-wide
# search). Commented out rather than deleted in case it's needed again for
# that kind of local testing.
#
# def discover_patient(
#     x_auth_token,
#     hiu_id,
#     hip_id,
#     identifier_type,
#     identifier_value,
# ):
#     """
#     Discover a patient for User Initiated Linking.
#     Args:
#         token (str): Gateway bearer token.
#         x_auth_token (str): X-AUTH-TOKEN issued by ABDM.
#         hiu_id (str): HIU identifier.
#         hip_id (str): HIP identifier.
#         identifier_type (str): Identifier type.
#                                Example: "ABHA_ADDRESS"
#         identifier_value (str): Identifier value.
#     Returns:
#         requests.Response
#     """
#
#     url = (
#         f"{HIECM_BASE_URL}"
#         "/user-initiated-linking/v3/patient/care-context/discover"
#     )
#
#     headers = {
#         "Authorization": f"Bearer {get_gateway_token()}",
#         "X-AUTH-TOKEN": f"Bearer {x_auth_token}",
#         "X-CM-ID": X_CM_ID,
#         "X-HIU-ID": hiu_id,
#         "REQUEST-ID": generate_request_id(),
#         "TIMESTAMP": generate_timestamp(),
#         "Content-Type": "application/json",
#     }
#
#     payload = {
#         "hipId": hip_id,
#         "unverifiedIdentifiers": [
#             {
#                 "type": identifier_type,
#                 "value": identifier_value,
#             }
#         ],
#     }
#
#     try:
#         response = requests.post(
#             url=url,
#             headers=headers,
#             json=payload,
#         )
#     except requests.exceptions.RequestException as exc:
#         log_error(f"Discover patient request failed: {exc}")
#         raise
#
#     return response

def send_on_discover(
    transaction_id,
    request_id,
    patient_data
):
    """
    Sends the on-discover response to ABDM Gateway.
    """

    url = (
        f"{HIECM_BASE_URL}"
        "/user-initiated-linking/v3/patient/care-context/on-discover"
    )

    payload = {
        "transactionId": transaction_id,
        "patient": patient_data,
        # TODO(flagged 2026-07): hardcoded to "MR" regardless of which
        # identifier actually matched the patient. Per the demo video,
        # this can legitimately be "MR" or "MOBILE" -- current code always
        # searches by ABHA address though, so this may not reflect reality.
        # Left as-is intentionally until confirmed; revisit if ABDM's
        # gateway ever rejects/complains about this value.
        "matchedBy": ["MR"],
        "response": {
            "requestId": request_id
        }
    }

    headers = {
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_gateway_token()}",
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="on-discover",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"on-discover call failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    record_call(
        label="on-discover",
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

def send_on_init(
    transaction_id,
    request_id,
    link_reference_number,
    authentication_type,
    communication_medium,
    communication_hint,
    communication_expiry,
):
    """
    Sends the on-init response to the ABDM Gateway.
    """

    url = (
        f"{HIECM_BASE_URL}"
        "/user-initiated-linking/v3/link/care-context/on-init"
    )

    payload = {
        "transactionId": transaction_id,
        "link": {
            "referenceNumber": link_reference_number,
            "authenticationType": authentication_type,
            "meta": {
                "communicationMedium": communication_medium,
                "communicationHint": communication_hint,
                "communicationExpiry": communication_expiry,
            },
        },
        "response": {
            "requestId": request_id,
        },
    }

    headers = {
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_gateway_token()}",
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="on-init",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"on-init call failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    record_call(
        label="on-init",
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

def send_on_confirm(
    patient,
    request_id,
):
    """
    Sends the ABDM on-confirm response.

    Args:
        patient (list): Patient array received during the Init callback.
        request_id (str): Request ID received in the Confirm callback.

    Returns:
        requests.Response
    """

    url = (
        f"{HIECM_BASE_URL}"
        "/user-initiated-linking/v3/link/care-context/on-confirm"
    )

    payload = {
        "patient": patient,
        "response": {
            "requestId": request_id
        }
    }

    headers = {
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_gateway_token()}",
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="on-confirm",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"on-confirm call failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    record_call(
        label="on-confirm",
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
