"""
HIU Consent Request APIs (M3 Block 1: Consent Init Request -> on-init ->
notify -> Consent Fetch -> on-fetch).

Like server/hip_linking.py's HIP-Initiated Linking flow, every outbound
call here is initiated BY US (as the HIU), not by ABDM, and is
acknowledged with 202 Accepted -- the real result is always delivered
later via a separate async callback (see
server/callbacks/services/consent_init_on_init_service.py,
consent_hiu_notify_service.py, consent_hiu_on_fetch_service.py).

This module is genuinely separate from server/hip_linking.py and from
M2's consent-notify code (server/healthinformation.py's
send_on_consent_notify, server/callbacks/services/consent_notify_service.py)
even though this codebase runs both HIP and HIU roles on the same server
for sandbox testing -- see this module's own functions for the confirmed,
per-endpoint differences (paths, headers, body shapes) that make sharing
code across the two roles unsafe here.
"""

import requests

from server.config import HIECM_BASE_URL, X_CM_ID
from server.utils import generate_request_id, generate_timestamp, get_gateway_token, call_with_retry
from server.callbacks.repository.pending_consent_request_repository import save_pending_consent_request
from server.callbacks.utils.flow_logger import log_error
from server.callbacks.utils.api_capture import record_call


def initiate_consent_request(
    hiu_id,
    patient_abha_address,
    requester_name,
    requester_identifier_type,
    requester_identifier_value,
    requester_identifier_system,
    purpose_text,
    purpose_code,
    purpose_ref_uri,
    hi_types,
    date_range_from,
    date_range_to,
    data_erase_at,
    hip_id=None,
    care_contexts=None,
):
    """
    Initiates an HIU Consent Request against ABDM (M3 Block 1, step 1):
    POST {HIECM_BASE_URL}/consent/v3/request/init.

    No X-HIU-ID header is sent on this specific call -- confirmed absent
    from the real "Milestone 3 - New" Postman collection's "Consent init
    Request" request; the hiu_id is only carried in the body's
    consent.hiu.id field.

    hip and careContexts are sent as literal JSON null -- confirmed by
    the same Postman example -- since at this point we (the HIU) don't
    yet know which HIP(s) hold the patient's records; ABDM/the patient's
    PHR app resolves that during the notify step.

    Success is 202 Accepted, with an ack-only body -- the real
    consentRequest.id is NOT returned here. It's delivered asynchronously
    via the on-init callback (POST /api/v3/hiu/consent/request/on-init),
    handled by
    server/callbacks/services/consent_init_on_init_service.py, which
    correlates back to this call's REQUEST-ID via
    pending_consent_request_repository.

    Failure scenarios for this endpoint were not part of this pass's
    confirmed reference material (no doc/Postman failure examples were
    supplied) -- not guessed or special-cased here. A non-202 response is
    just logged with its raw status/body and returned for the caller to
    inspect, same as every other outbound call in this codebase.

    Args:
        hiu_id (str): Our HIU identifier, sent as consent.hiu.id.
        patient_abha_address (str): Patient's ABHA address, sent as
            consent.patient.id.
        requester_name (str): Name of the individual/system requesting
            this consent, sent as consent.requester.name.
        requester_identifier_type (str): consent.requester.identifier.type.
        requester_identifier_value (str): consent.requester.identifier.value.
        requester_identifier_system (str): consent.requester.identifier.system.
        purpose_text (str): consent.purpose.text.
        purpose_code (str): consent.purpose.code.
        purpose_ref_uri (str): consent.purpose.refUri.
        hi_types (list): consent.hiTypes -- list of HI type strings.
        date_range_from (str): consent.permission.dateRange.from (ISO 8601).
        date_range_to (str): consent.permission.dateRange.to (ISO 8601).
        data_erase_at (str): consent.permission.dataEraseAt (ISO 8601).
        hip_id (str, optional): consent.hip.id -- scopes the request to ONE
            hospital instead of all of them. ADDED for the Health Locker
            flow (aegle-phr's P19): an 8.3.11 LINK alert names the exact
            HIP whose care contexts just became available, and the consent
            the locker raises in response should cover that HIP, not
            everything. Defaults to None, which sends "hip": null exactly
            as this function always has -- every existing caller is
            unaffected.
        care_contexts (list, optional): consent.careContexts -- the
            specific care contexts to scope to, each
            {"patientReference": ..., "careContextReference": ...}, as
            carried by the same alert. Defaults to None, sending
            "careContexts": null, unchanged from before.
    Returns:
        requests.Response: The raw consent/v3/request/init response (202
            expected).
    Raises:
        requests.exceptions.RequestException: If the request fails
            (network error or non-2xx response).
    """

    request_id = generate_request_id()

    # Stashed before the request is made, so the pending session exists
    # even if a slow/edge-case on-init callback arrives before this
    # function returns -- same reasoning as hip_linking.py's own pending
    # session saves.
    save_pending_consent_request(
        request_id,
        {
            "hiu_id": hiu_id,
            "patient_abha_address": patient_abha_address,
        },
    )

    url = f"{HIECM_BASE_URL}/consent/v3/request/init"

    payload = {
        "consent": {
            "purpose": {
                "text": purpose_text,
                "code": purpose_code,
                "refUri": purpose_ref_uri,
            },
            "patient": {
                "id": patient_abha_address,
            },
            "hiu": {
                "id": hiu_id,
            },
            # Both default to None -- the shape this call has always sent.
            # Populated only when a caller explicitly scopes the request to
            # one hospital / specific care contexts (the Health Locker's
            # own LINK-alert path). See this function's own Args.
            "hip": {"id": hip_id} if hip_id else None,
            "careContexts": care_contexts if care_contexts else None,
            "requester": {
                "name": requester_name,
                "identifier": {
                    "type": requester_identifier_type,
                    "value": requester_identifier_value,
                    "system": requester_identifier_system,
                },
            },
            "hiTypes": hi_types,
            "permission": {
                "accessMode": "VIEW",
                "dateRange": {
                    "from": date_range_from,
                    "to": date_range_to,
                },
                "dataEraseAt": data_erase_at,
                "frequency": {
                    "unit": "HOUR",
                    "value": 0,
                    "repeats": 0,
                },
            },
        }
    }

    headers = {
        "REQUEST-ID": request_id,
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
        "Authorization": f"Bearer {get_gateway_token()}",
        "Content-Type": "application/json",
    }

    # RETRY: category 2 is a connection error/timeout or a 5xx/429/408
    # response -- see call_with_retry(). Not an ack -- this is the
    # initiating call, same request_id reused across retry attempts.
    # IDEMPOTENCY (unconfirmed): whether ABDM treats a same-REQUEST-ID
    # resubmission of a fresh consent request as safe (no duplicate
    # consent-request created) is not documented anywhere in this
    # module's own reference material (its docstring already notes
    # "failure scenarios for this endpoint were not part of this pass's
    # confirmed reference material") -- flagged, not assumed.
    try:
        response = call_with_retry(
            lambda: requests.post(
                url=url,
                json=payload,
                headers=headers,
                timeout=30,
            ),
            description="Consent init request",
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="initiate-consent-request",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"Consent init request failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    if response.status_code != 202:
        log_error(
            f"Consent init request returned unexpected status "
            f"{response.status_code}: {response_body}"
        )

    record_call(
        label="initiate-consent-request",
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


def send_consent_hiu_on_notify(acknowledgements, request_id):
    """
    Acknowledges the HIU Consent Notify callback back to ABDM (M3 Block
    1, step 3's ack): POST {HIECM_BASE_URL}/consent/v3/request/hiu/on-notify.

    Structurally similar to M2's send_on_consent_notify()
    (server/healthinformation.py), which acks the HIP-side notify
    callback -- but a genuinely different endpoint (different path,
    different HIU-vs-HIP role) with a different body shape: this one's
    "acknowledgement" is a LIST of {"status", "consentId"} objects (one
    per consent artefact carried in the notify payload, since a single
    notification can grant more than one HIP's artefact at once), not the
    single object M2's endpoint sends. Confirmed via the real
    "Milestone 3 - New" Postman collection's "Consent HIU on notify"
    request. No X-HIU-ID header on this outbound call either -- also
    confirmed absent from that same Postman request.

    Args:
        acknowledgements (list): [{"status": str, "consentId": str}, ...]
            -- one entry per consent artefact being acknowledged.
        request_id (str): The REQUEST-ID header value from the inbound
            notify callback being acknowledged (echoed back as
            response.requestId, matching the ack convention used
            elsewhere in this codebase).
    Returns:
        requests.Response: The raw hiu/on-notify response (202 expected).
    Raises:
        requests.exceptions.RequestException: If the request fails
            (network error or non-2xx response).
    """

    url = f"{HIECM_BASE_URL}/consent/v3/request/hiu/on-notify"

    payload = {
        "acknowledgement": acknowledgements,
        "response": {
            "requestId": request_id,
        },
    }

    headers = {
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
        "Authorization": f"Bearer {get_gateway_token()}",
        "Content-Type": "application/json",
    }

    # RETRY: category 2 is a connection error/timeout or a 5xx/429/408
    # response -- see call_with_retry(). Ack of an inbound HIU consent
    # notify callback -- but consent_hiu_notify_service.py's
    # process_consent_hiu_notify() is NOT currently wired to the
    # idempotency guard (server/callbacks/utils/idempotency.py, only
    # consent_notify is, per that module's own docstring) -- so, unlike
    # send_on_consent_notify() in server/healthinformation.py, a
    # duplicate ack here isn't as cleanly confirmed-safe. Retried anyway
    # per the retry-logic spec's uniform ack policy -- flagged, not
    # silently assumed.
    try:
        response = call_with_retry(
            lambda: requests.post(
                url=url,
                json=payload,
                headers=headers,
                timeout=30,
            ),
            description="Consent HIU on-notify ack",
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="consent-hiu-on-notify",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"Consent HIU on-notify ack failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    if response.status_code != 202:
        log_error(
            f"Consent HIU on-notify ack returned unexpected status "
            f"{response.status_code}: {response_body}"
        )

    record_call(
        label="consent-hiu-on-notify",
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


def fetch_consent(hiu_id, consent_id):
    """
    Requests the full consent artefact detail from ABDM (M3 Block 1,
    step 4): POST {HIECM_BASE_URL}/consent/v3/fetch.

    Success is 202 Accepted -- the real consent detail (consentDetail +
    signature) is NOT returned here. It's delivered asynchronously via
    the on-fetch callback (POST /api/v3/hiu/consent/on-fetch), handled by
    server/callbacks/services/consent_hiu_on_fetch_service.py, which
    stores it in hiu_consent_repository keyed by
    consent.consentDetail.consentId.

    Failure scenarios for this endpoint were not part of this pass's
    confirmed reference material -- not guessed or special-cased here. A
    non-202 response is just logged with its raw status/body and returned
    for the caller to inspect.

    Args:
        hiu_id (str): Our HIU identifier, sent as the X-HIU-ID header.
        consent_id (str): The consent artefact id being fetched (one
            entry from a GRANTED notify callback's consentArtefacts).
    Returns:
        requests.Response: The raw consent/v3/fetch response (202
            expected).
    Raises:
        requests.exceptions.RequestException: If the request fails
            (network error or non-2xx response).
    """

    request_id = generate_request_id()

    # Stashed before the request is made, mirroring hip_linking.py's
    # save-before-call pattern -- kept minimal since the on-fetch
    # callback body already carries the full consentId, so there's
    # nothing else to correlate back on the way in.
    save_pending_consent_request(
        request_id,
        {
            "hiu_id": hiu_id,
            "consent_id": consent_id,
        },
    )

    url = f"{HIECM_BASE_URL}/consent/v3/fetch"

    payload = {
        "consentId": consent_id,
    }

    headers = {
        "REQUEST-ID": request_id,
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
        "X-HIU-ID": hiu_id,
        "Authorization": f"Bearer {get_gateway_token()}",
        "Content-Type": "application/json",
    }

    # RETRY: category 2 is a connection error/timeout or a 5xx/429/408
    # response -- see call_with_retry(). Not an ack -- this is the
    # initiating fetch call, same request_id reused across retry
    # attempts. IDEMPOTENCY (unconfirmed): re-fetching the same
    # already-fetched consentId is presumed low-risk (a read of
    # already-granted consent detail, not a state mutation) but this is
    # an inference, not a confirmed ABDM guarantee -- flagged rather than
    # assumed.
    #
    # COMPOSES WITH THE M3-26 FIX (consent_hiu_notify_service.py's
    # per-artefact try/except around this call): retrying happens
    # entirely INSIDE this function, before it ever returns or raises --
    # so from that caller's point of view nothing changes. If every
    # attempt here is exhausted while still transient, this function
    # raises/returns exactly what it always did on a single failed
    # attempt (a raised RequestException, or a non-202 response logged
    # via the `if response.status_code != 202` check below); the
    # per-artefact try/except still catches the raised case the same way,
    # and the other artefacts in the same multi-hospital consent grant
    # still get their own fetch_consent() call (and their own independent
    # up-to-3-attempt retry budget) regardless of how this one went.
    try:
        response = call_with_retry(
            lambda: requests.post(
                url=url,
                json=payload,
                headers=headers,
                timeout=30,
            ),
            description="Consent fetch",
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="fetch-consent",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"Consent fetch failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    if response.status_code != 202:
        log_error(
            f"Consent fetch returned unexpected status "
            f"{response.status_code}: {response_body}"
        )

    record_call(
        label="fetch-consent",
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
