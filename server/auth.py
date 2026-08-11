"""
Authentication-related functions for ABDM APIs.
"""

import requests

from server.config import (
    CALLBACK_URL,
    CLIENT_ID,
    CLIENT_SECRET,
    GATEWAY_BASE_URL,
    X_CM_ID,
)

from server.utils import generate_request_id, generate_timestamp, get_gateway_token
from server.callbacks.utils.flow_logger import log_error
from server.callbacks.utils.api_capture import record_call

def generate_gateway_token():

    """
    Generate an ABDM Gateway access token.
    Returns:
        requests.Response: Gateway token response.
    Raises:
        requests.exceptions.RequestException: If the request fails
            (network error or non-2xx response).
    """

    url = f"{GATEWAY_BASE_URL}/sessions"

    payload = {
        "clientId": CLIENT_ID,
        "clientSecret": CLIENT_SECRET,
        "grantType": "client_credentials",
    }

    headers = {
        "Content-Type": "application/json",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
    }

    try:
        response = requests.post(
            url=url,
            json=payload,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        record_call(
            label="generate-gateway-token",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"Gateway token generation failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    record_call(
        label="generate-gateway-token",
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

def update_bridge_url(callback_url=None):

    """
    Register/update our callback (bridge) URL with the ABDM Gateway, so
    ABDM knows where to send callbacks -- e.g. when the ngrok tunnel URL
    changes during sandbox testing.

    Success is confirmed by the official M2 documentation (§3.2.4 "Update
    bridge URL API") as a 202 Accepted with an empty body. The shape of a
    failure response for this specific endpoint is NOT confirmed anywhere
    yet.

    Args:
        callback_url (str, optional): Callback URL to register. Defaults
            to config.CALLBACK_URL if not provided.
    Returns:
        requests.Response: Bridge URL update response.
    Raises:
        requests.exceptions.RequestException: If the request fails
            (network error or non-2xx response).
    """

    if callback_url is None:
        callback_url = CALLBACK_URL

    url = f"{GATEWAY_BASE_URL}/bridge/url"

    payload = {
        "url": callback_url,
    }

    headers = {
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_gateway_token()}",
    }

    try:
        response = requests.patch(
            url=url,
            json=payload,
            headers=headers,
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="update-bridge-url",
            direction="outgoing",
            method="PATCH",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"Bridge URL update failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    # NOTE: only the 202 success shape is confirmed (official doc, empty
    # body). The failure response shape for this endpoint is unconfirmed,
    # so we don't assume anything about response_body here -- just log it
    # as-is and let the caller inspect the response themselves.
    if response.status_code != 202:
        log_error(
            f"Bridge URL update returned unexpected status "
            f"{response.status_code}: {response_body}"
        )

    record_call(
        label="update-bridge-url",
        direction="outgoing",
        method="PATCH",
        url=url,
        request_headers=headers,
        request_body=payload,
        response_status=response.status_code,
        response_headers=dict(response.headers),
        response_body=response_body,
    )

    return response

def find_bridge_service_by_id(service_id):

    """
    Look up a registered bridge service in the ABDM Gateway by its
    service ID.

    Success is confirmed by the official M2 documentation (§3.2.6 "Find
    bridge by service id") as a 200 OK with the following fields:
        id, bridgeId, serviceId, name, isHip, isHiu, isPhr, endpoints,
        active, registerTime, dateCreated, dateModified.

    The response for a service ID that doesn't exist or isn't registered
    is NOT confirmed anywhere (neither the doc nor the saved Postman
    request has an example of that case) -- no not-found status code or
    body shape is assumed here.

    Args:
        service_id (str): Service ID to look up (ABDM's serviceId,
            e.g. "TestClinicHIP").
    Returns:
        requests.Response: Bridge service lookup response.
    Raises:
        requests.exceptions.RequestException: If the request fails
            (network error or non-2xx response).
    """

    url = f"{GATEWAY_BASE_URL}/bridge-service/serviceId/{service_id}"

    headers = {
        "Authorization": f"Bearer {get_gateway_token()}",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
    }

    try:
        response = requests.get(
            url=url,
            headers=headers,
            timeout=30,
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="find-bridge-service-by-id",
            direction="outgoing",
            method="GET",
            url=url,
            request_headers=headers,
            request_body=None,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"Bridge service lookup failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    # NOTE: only the 200 success shape is confirmed (official doc). The
    # not-found/error response shape for this endpoint is unconfirmed,
    # so we don't assume anything about response_body here -- just log
    # it as-is and let the caller inspect the response themselves.
    if response.status_code != 200:
        log_error(
            f"Bridge service lookup returned unexpected status "
            f"{response.status_code}: {response_body}"
        )

    record_call(
        label="find-bridge-service-by-id",
        direction="outgoing",
        method="GET",
        url=url,
        request_headers=headers,
        request_body=None,
        response_status=response.status_code,
        response_headers=dict(response.headers),
        response_body=response_body,
    )

    return response

def find_services_by_bridge_id():

    """
    Look up all services registered under our own bridge in the ABDM
    Gateway. ABDM resolves which bridge from the Authorization token
    itself -- there is no bridgeId parameter anywhere in the request.

    CORRECTED (2026-08-04): this function previously appended bridge_id
    as a URL path segment (`/bridge-services/{bridgeId}`), and the M2 doc
    page for this API was written the same way. That was based on a
    stale saved Postman *example response* (from "Milestone 2 - New"),
    captured from a request whose URL had been manually edited with a
    path segment (`/bridge-services/SBX_002167` -- not even our own
    bridge ID) before sending, not from the collection's actual live
    request template. The live template -- and a real user-confirmed
    test run -- is `/bridge-services` with nothing appended.

    Confirmed by the official M2 documentation (§3.2.7 "Find services by
    bridge id") and by the actual Postman collection request template, as
    a 200 OK with:
        bridge: {id, name, url, active, blocklisted}
        services: [{id, name, types, endpoints: {hipEndpoints, hiuEndpoints,
            healthLockerEndpoints}, active}, ...]

    A 403 Forbidden failure (plain text body "Access Denied") is also
    confirmed from a real captured example, triggered when X-CM-ID was
    sent empty.

    Returns:
        requests.Response: Bridge services lookup response.
    Raises:
        requests.exceptions.RequestException: If the request fails
            (network error or non-2xx response).
    """

    url = f"{GATEWAY_BASE_URL}/bridge-services"

    headers = {
        "Authorization": f"Bearer {get_gateway_token()}",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
    }

    try:
        response = requests.get(
            url=url,
            headers=headers,
            timeout=30,
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="find-services-by-bridge-id",
            direction="outgoing",
            method="GET",
            url=url,
            request_headers=headers,
            request_body=None,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"Bridge services lookup failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    if response.status_code != 200:
        log_error(
            f"Bridge services lookup returned unexpected status "
            f"{response.status_code}: {response_body}"
        )

    record_call(
        label="find-services-by-bridge-id",
        direction="outgoing",
        method="GET",
        url=url,
        request_headers=headers,
        request_body=None,
        response_status=response.status_code,
        response_headers=dict(response.headers),
        response_body=response_body,
    )

    return response
