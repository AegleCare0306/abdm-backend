import requests

from server.config import HIECM_BASE_URL, X_CM_ID
from server.utils import generate_request_id, generate_timestamp, get_gateway_token, call_with_retry
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

    # RETRY: category 2 is a connection error/timeout or a 5xx/429/408
    # response -- see call_with_retry(). Ack of an inbound consent-notify
    # callback -- server/callbacks/services/consent_notify_service.py IS
    # wired to the idempotency guard (server/callbacks/utils/idempotency.py,
    # tracker case M2-9), so a duplicate ack here is safe: ABDM's own
    # retry of the underlying notify would just hit our idempotency check
    # and produce the same re-ack behavior either way.
    try:
        response = call_with_retry(
            lambda: requests.post(
                url=url,
                headers=headers,
                json=payload,
                timeout=30,
            ),
            description="on-notify (consent) ack",
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

    # RETRY: category 2 is a connection error/timeout or a 5xx/429/408
    # response -- see call_with_retry(). Ack of an inbound
    # health-information-request callback. UNLIKE send_on_consent_notify()
    # above, the handler for this inbound callback
    # (server/callbacks/services/health_information_request_service.py)
    # is NOT currently wired to the idempotency guard (only consent_notify
    # is, per idempotency.py's own module docstring) -- so whether a
    # duplicate ack here is truly harmless is not as cleanly confirmed as
    # the consent-notify case. Retried anyway per the retry-logic spec's
    # explicit choice to apply the same policy to every ack call
    # uniformly -- flagged here, not silently assumed safe.
    try:
        response = call_with_retry(
            lambda: requests.post(
                url=url,
                headers=headers,
                json=payload,
                timeout=30,
            ),
            description="on-request (health information) ack",
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
    attachment_mechanisms=None,
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
        attachment_mechanisms (list[str] | None): which FHIR attachment
            mechanism(s) were present across the bundle(s) behind these
            (already-encrypted) entries -- passed straight through to
            record_call() so storage/api_capture.jsonl can be correlated
            against attachment mechanism later. Purely instrumentation;
            doesn't affect the actual push.

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

    # RETRY: category 2 is a connection error/timeout or a 5xx/429/408
    # response -- see call_with_retry(). NOT an ack -- this is the actual
    # PHI data-push call, to a URL supplied by the inbound request
    # (data_push_url), not ABDM's own gateway. IDEMPOTENCY (unconfirmed,
    # explicitly flagged): the payload -- including key_material -- is
    # built once by the caller and unchanged across retry attempts of
    # this one call, so a retry resends byte-identical ciphertext, not a
    # second independent push under a different key. Whether the
    # receiving HIU treats a duplicate push of the same transactionId/
    # entries as a safe no-op is NOT confirmed here -- this codebase's
    # own HIU-side receiver (health_information_hiu_push_service.py's
    # process_health_information_hiu_push()) happens to merge
    # care_contexts by careContextReference, which is naturally tolerant
    # of a duplicate, but a real third-party HIU's behavior is unknown.
    # Retried anyway per the retry-logic spec's explicit choice to apply
    # the same policy uniformly -- flagged for Aayush, not assumed safe.
    try:
        response = call_with_retry(
            lambda: requests.post(
                url=data_push_url,
                headers=headers,
                json=payload,
                timeout=30,
            ),
            description="Data push to HIU",
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
            attachment_mechanisms=attachment_mechanisms,
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
        attachment_mechanisms=attachment_mechanisms,
    )

    return response


def send_health_information_notify(
    consent_id,
    transaction_id,
    hip_id,
    done_at,
    session_status,
    status_responses,
    notifier_type="HIP",
    notifier_id=None,
):
    """
    Notifies the CM of the outcome of a health information transfer.

    Shared by both roles this codebase runs -- M2 (the HIP, notifying
    that it PUSHED data to an HIU) and M3 Block 2 (the HIU, notifying
    that it RECEIVED data from an HIP) -- confirmed via the "Milestone 3
    - New" Postman collection that the payload shape is identical between
    the HIP-sent and HIU-sent versions, with only notifier.type/
    notifier.id differing by role; statusNotification.hipId stays
    HIP-scoped regardless of who's calling. Added 2026-08-10 for M3;
    notifier_type/notifier_id default to M2's original, only behavior
    (notifier.type="HIP", notifier.id=hip_id) so both of M2's existing
    call sites (server/callbacks/services/health_information_request_service.py)
    are completely unchanged.

    Args:
        consent_id (str)
        transaction_id (str)
        hip_id (str): Always the HIP's own id, regardless of caller role
            -- goes into statusNotification.hipId either way.
        done_at (str): ISO 8601 timestamp of when the transfer completed.
        session_status (str): M2's HIP-role vocabulary is TRANSFERRED/
            FAILED; M3's HIU-role vocabulary is RECEIVED/FAILED --
            confirmed as genuinely different per-role values (each role's
            own Postman example), not unified here.
        status_responses (list): [{careContextReference, hiStatus, description}, ...]
            hiStatus is one of DELIVERED, ERRORED (per the doc's prose --
            flagged separately as an open question against the doc's own
            example, which shows "OK" instead; using DELIVERED/ERRORED per
            team decision).
        notifier_type (str): "HIP" (default, M2's original behavior) or
            "HIU" (M3 Block 2's health_information_hiu_push_service.py).
        notifier_id (str | None): Defaults to hip_id (M2's original
            behavior) when not given. M3 passes its own hiu_id here.

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
                "type": notifier_type,
                "id": notifier_id or hip_id,
            },
            "statusNotification": {
                "sessionStatus": session_status,
                "hipId": hip_id,
                "statusResponses": status_responses,
            },
        }
    }

    # RETRY: category 2 is a connection error/timeout or a 5xx/429/408
    # response -- see call_with_retry(). A completion notification, not a
    # strict ack of one specific inbound message. IDEMPOTENCY
    # (unconfirmed): neither caller of this function
    # (health_information_request_service.py's M2 push-and-notify, or
    # health_information_hiu_push_service.py's M3 push handler) is wired
    # to the idempotency guard -- flagged, not assumed safe. Retried per
    # the retry-logic spec's uniform policy regardless.
    try:
        response = call_with_retry(
            lambda: requests.post(
                url=url,
                headers=headers,
                json=payload,
                timeout=30,
            ),
            description="Health Information notify",
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
