"""
HIU Health Information Request (M3 Block 2: Health Information Request ->
on-request ack -> data push (HIP -> our dataPushUrl, direct, not through
the ABDM gateway) -> notify).

Mirrors server/hiu_consent.py's structure/conventions -- see that
module's own docstring for the shared HIU-outbound-call pattern (202
Accepted ack, real result via a later async callback).

TWO FLAGGED ITEMS IN THIS MODULE (surfaced in the implementation prompt's
own report, not just here -- read both before live sandbox testing):

1. Body shape ambiguity (partially confirmed): the Postman collection's
   saved EXAMPLE response for the Health Information Request call shows
   extra top-level requestId/timestamp fields in the request body, but
   the request-definition TEMPLATE (and, more tellingly, M2's own
   process_health_information_request() -- which receives the
   mirror-image of this exact call as the HIP, and only ever reads
   request-id from the HEADER, never from the body) both suggest there
   are no top-level body fields. initiate_health_information_request()
   below goes with the template shape (no top-level requestId/timestamp)
   -- a judgment call based on cross-referencing the mirror side of the
   same call, not a fully confirmed fact.

2. Outbound key format (NOT confirmed the way this module's original
   spec assumed -- flagging a discrepancy found while implementing):
   the spec for this module said to send our own public key in X.509 DER
   format (to_x509_public_key()), citing "confirmed in M2." Reading M2's
   own code (server/callbacks/services/health_information_request_service.py's
   _push_and_notify()) shows the OPPOSITE for this specific direction:
   its comment says "The INCOMING HIU key stays raw uncompressed (that
   direction is confirmed correct already)" -- i.e. M2 reads the
   INCOMING HIU-supplied key (hiRequest.keyMaterial.dhPublicKey.keyValue,
   exactly what initiate_health_information_request() below sends)
   directly, with NO from_x509 conversion applied, and that was
   confirmed correct via real sandbox testing while fixing a genuine
   ABDM-9999 error (which turned out to be caused ONLY by M2's own
   OUTBOUND push key needing X.509, not by the incoming HIU key). Given
   this direct, in-code evidence, this module sends our own key RAW
   (unconverted) below, NOT X.509-converted -- deviating from this
   module's original spec. This is a judgment call, not a fully
   confirmed fact either way; flagged prominently for live sandbox
   verification, same as item 1.
"""

import requests

from server.config import HIECM_BASE_URL, X_CM_ID, CALLBACK_URL
from server.utils import generate_request_id, generate_timestamp, get_gateway_token, generate_expiry_time
from server.fidelius_crypto import generate_key_material
from server.callbacks.repository.pending_health_information_request_repository import save_pending_health_information_request
from server.callbacks.utils.flow_logger import log_error
from server.callbacks.utils.api_capture import record_call


def initiate_health_information_request(
    hiu_id,
    consent_id,
    hip_id,
    date_range_from,
    date_range_to,
):
    """
    Initiates an HIU Health Information Request against ABDM (M3 Block 2,
    step 1): POST {HIECM_BASE_URL}/data-flow/v3/health-information/request.

    Generates a fresh ECDH key pair + nonce for this transaction
    (fidelius_crypto.generate_key_material() -- per Fidelius's
    forward-secrecy design, never reused across transactions, same as
    M2's own key generation for its outbound push) and a dataPushUrl
    pointing back at our own /api/v3/hiu/health-information/push route
    (server/callbacks/router.py) -- built from CALLBACK_URL fresh on
    every call (not cached at import time) so an updated ngrok tunnel URL
    in server/config.py takes effect without needing this module
    reloaded separately, matching how server/auth.py reads CALLBACK_URL.

    See this module's own docstring for two flagged, not-fully-confirmed
    judgment calls made in the body/key-format below.

    Success is 202 Accepted, ack-only -- the real transactionId is NOT
    returned here. It's delivered asynchronously via the on-request
    callback (POST /api/v3/hiu/health-information/on-request -- confirmed
    via the M3 spec doc's section 5.3.2, see server/callbacks/router.py's
    own comment on that route), handled by
    server/callbacks/services/health_information_hiu_on_request_service.py,
    which correlates back to this call's REQUEST-ID via
    pending_health_information_request_repository.

    Failure scenarios for this endpoint were not part of this pass's
    confirmed reference material -- not guessed or special-cased here. A
    non-202 response is just logged with its raw status/body and
    returned for the caller to inspect.

    Args:
        hiu_id (str): Our HIU identifier, sent as the X-HIU-ID header.
        consent_id (str): The GRANTED consent artefact id this request is
            for (from hiu_consent_repository).
        hip_id (str): The HIP holding this patient's records, per the
            consent artefact's own consentDetail.hip.id -- not sent in
            this call's body (ABDM already knows which HIP(s) a given
            consentId covers), but stashed in the pending session so the
            eventual notify call (step 4) has it without needing a second
            lookup.
        date_range_from (str): hiRequest.dateRange.from (ISO 8601) --
            must fall within the consent's own approved dateRange.
        date_range_to (str): hiRequest.dateRange.to (ISO 8601).
    Returns:
        requests.Response: The raw health-information/request response
            (202 expected).
    Raises:
        requests.exceptions.RequestException: If the request fails
            (network error or non-2xx response).
    """

    key_material = generate_key_material()
    request_id = generate_request_id()

    # Stashed before the request is made, so the pending session exists
    # even if a slow/edge-case on-request callback arrives before this
    # function returns -- same reasoning as hiu_consent.py's own pending
    # session saves. key_material (including our own private key/nonce)
    # is kept here specifically because the data push in step 3 needs it
    # to decrypt what the HIP sends -- it is never sent back to us by
    # ABDM.
    save_pending_health_information_request(
        request_id,
        {
            "hiu_id": hiu_id,
            "consent_id": consent_id,
            "hip_id": hip_id,
            "key_material": key_material,
            "date_range": {"from": date_range_from, "to": date_range_to},
        },
    )

    url = f"{HIECM_BASE_URL}/data-flow/v3/health-information/request"

    data_push_url = f"{CALLBACK_URL}/api/v3/hiu/health-information/push"

    payload = {
        "hiRequest": {
            "consent": {"id": consent_id},
            "dateRange": {"from": date_range_from, "to": date_range_to},
            "dataPushUrl": data_push_url,
            "keyMaterial": {
                "cryptoAlg": "ECDH",
                "curve": "Curve25519",
                "dhPublicKey": {
                    "expiry": generate_expiry_time(minutes=60),
                    "parameters": "Curve25519/32byte random key",
                    # FLAGGED (module docstring, item 2): sent RAW here,
                    # NOT to_x509_public_key()-converted -- see that
                    # docstring for the in-code evidence this is based on.
                    "keyValue": key_material["public_key"],
                },
                "nonce": key_material["nonce"],
            },
        }
        # FLAGGED (module docstring, item 1): no top-level requestId/
        # timestamp fields here -- going with the request-definition
        # template shape, not the saved example response's shape.
    }

    headers = {
        "REQUEST-ID": request_id,
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": X_CM_ID,
        "X-HIU-ID": hiu_id,
        "Authorization": f"Bearer {get_gateway_token()}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            url=url,
            json=payload,
            headers=headers,
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="initiate-health-information-request",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"Health information request failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    if response.status_code != 202:
        log_error(
            f"Health information request returned unexpected status "
            f"{response.status_code}: {response_body}"
        )

    record_call(
        label="initiate-health-information-request",
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
