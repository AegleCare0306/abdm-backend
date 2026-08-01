import requests

from server.config import HIECM_BASE_URL, X_CM_ID
from server.utils import generate_request_id, generate_timestamp, get_gateway_token
from server.callbacks.utils.flow_logger import log_error
from server.callbacks.utils.api_capture import record_call


def send_on_consent_notify(
    consent_id,
    request_id,
    status="OK",
):
    """
    Sends acknowledgement for Consent Notify callback.

    Args:
        consent_id (str)
        request_id (str)
        status (str)

    Returns:
        requests.Response
    """

    url = (
        f"{HIECM_BASE_URL}"
        "/consent/v3/request/hip/on-notify"
    )

    headers = {
        "Authorization": f"Bearer {get_gateway_token()}",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
        "Content-Type": "application/json",
    }

    payload = {
        "acknowledgement": {
            "status": status,
            "consentId": consent_id,
        },
        "response": {
            "requestId": request_id,
        },
    }

    try:
        response = requests.post(
            url=url,
            headers=headers,
            json=payload,
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="on-notify-consent",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"on-notify (consent) call failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    record_call(
        label="on-notify-consent",
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

def send_on_health_information_request(
    transaction_id,
    request_id,
    session_status="ACKNOWLEDGED",
):
    """
    Acknowledges receipt of a Health Information Request.

    Args:
        transaction_id (str)
        request_id (str)
        session_status (str)

    Returns:
        requests.Response
    """

    url = (
        f"{HIECM_BASE_URL}"
        "/data-flow/v3/health-information/hip/on-request"
    )

    headers = {
        "Authorization": f"Bearer {get_gateway_token()}",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
        "Content-Type": "application/json",
    }

    payload = {
        "hiRequest": {
            "transactionId": transaction_id,
            "sessionStatus": session_status,
        },
        "response": {
            "requestId": request_id,
        },
    }

    try:
        response = requests.post(
            url=url,
            headers=headers,
            json=payload,
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="on-request-health-information",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"on-request (health information) call failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    record_call(
        label="on-request-health-information",
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


def send_health_information_data(
    data_push_url,
    transaction_id,
    entries,
    key_material,
    page_number=0,
    page_count=1,
):
    """
    Pushes encrypted health information entries to the HIU's dataPushUrl.

    NOTE: unlike every other call in this codebase, this goes to the HIU's
    own URL (given per-request in hiRequest.dataPushUrl), not ABDM's
    gateway -- so it uses only Content-Type + Authorization headers,
    matching the reference sample provided for this specific endpoint
    (no REQUEST-ID/TIMESTAMP/X-CM-ID, unlike the HIECM-bound calls above).

    Args:
        data_push_url (str): The dataPushUrl from the original
            Health Information Request.
        transaction_id (str)
        entries (list): [{content, media, checksum, careContextReference}, ...]
        key_material (dict): Our own generated key material
            (cryptoAlg, curve, dhPublicKey, nonce) -- NOT the HIU's.
        page_number (int)
        page_count (int)

    Returns:
        requests.Response
    """

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_gateway_token()}",
    }

    payload = {
        "pageNumber": page_number,
        "pageCount": page_count,
        "transactionId": transaction_id,
        "entries": entries,
        "keyMaterial": key_material,
    }

    try:
        response = requests.post(
            url=data_push_url,
            headers=headers,
            json=payload,
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="data-push-to-hiu",
            direction="outgoing",
            method="POST",
            url=data_push_url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"Data push to HIU ({data_push_url}) failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    record_call(
        label="data-push-to-hiu",
        direction="outgoing",
        method="POST",
        url=data_push_url,
        request_headers=headers,
        request_body=payload,
        response_status=response.status_code,
        response_headers=dict(response.headers),
        response_body=response_body,
    )

    return response


def send_health_information_notify(
    consent_id,
    transaction_id,
    hip_id,
    done_at,
    session_status,
    status_responses,
):
    """
    Notifies the CM of the outcome of a health information transfer.

    Args:
        consent_id (str)
        transaction_id (str)
        hip_id (str)
        done_at (str): ISO 8601 timestamp of when the transfer completed.
        session_status (str): One of TRANSFERRED, FAILED.
        status_responses (list): [{careContextReference, hiStatus, description}, ...]
            hiStatus is one of DELIVERED, ERRORED (per the doc's prose --
            flagged separately as an open question against the doc's own
            example, which shows "OK" instead; using DELIVERED/ERRORED per
            team decision).

    Returns:
        requests.Response
    """

    url = (
        f"{HIECM_BASE_URL}"
        "/data-flow/v3/health-information/notify"
    )

    headers = {
        "Authorization": f"Bearer {get_gateway_token()}",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
        "Content-Type": "application/json",
    }

    payload = {
        "notification": {
            "consentId": consent_id,
            "transactionId": transaction_id,
            "doneAt": done_at,
            "notifier": {
                "type": "HIP",
                "id": hip_id,
            },
            "statusNotification": {
                "sessionStatus": session_status,
                "hipId": hip_id,
                "statusResponses": status_responses,
            },
        }
    }

    try:
        response = requests.post(
            url=url,
            headers=headers,
            json=payload,
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="health-information-notify",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"Health Information notify call failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    record_call(
        label="health-information-notify",
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
