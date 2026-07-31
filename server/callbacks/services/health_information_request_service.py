import hashlib
import json

from server.callbacks.repository.health_information_repository import save_health_information_session
from server.callbacks.repository.consent_repository import get_consent
from server.callbacks.services.health_information_data_service import build_bundles_for_care_contexts
from server.healthinformation import (
    send_on_health_information_request,
    send_health_information_data,
    send_health_information_notify,
)
from server.fidelius_crypto import generate_key_material, encrypt_health_data, to_x509_public_key
from server.utils import print_api_response, generate_timestamp, generate_expiry_time, generate_safe_past_timestamp
from server.callbacks.utils.flow_logger import log_phase, log_api_call, log_waiting, log_error


def _compute_checksum(encrypted_content):
    """
    MD5 hex digest of the encrypted content. Confirmed (not guessed) via an
    independent source documenting real ABDM HIP integrations -- an earlier
    version of this used SHA-256 as an unconfirmed placeholder; that was
    wrong. This resolves the same "what should checksum be" question that
    came up earlier around the "string" ambiguity from the demo video.
    """
    return hashlib.md5(encrypted_content.encode("utf-8")).hexdigest()


def _push_and_notify(
    fhir_bundles,
    care_context_references,
    data_push_url,
    hiu_key_material,
    transaction_id,
    consent_id,
    hip_id,
):

    entries = []
    status_responses = []

    hip_key_material = generate_key_material()

    for bundle, care_context_reference in zip(fhir_bundles, care_context_references):

        plaintext = json.dumps(bundle)

        try:
            encrypted_content = encrypt_health_data(
                plaintext=plaintext,
                sender_private_key=hip_key_material["private_key"],
                sender_nonce=hip_key_material["nonce"],
                requester_public_key=hiu_key_material["dhPublicKey"]["keyValue"],
                requester_nonce=hiu_key_material["nonce"],
            )
        except Exception as exc:
            log_error(f"Encryption failed for care context {care_context_reference}: {exc}")
            status_responses.append({
                "careContextReference": care_context_reference,
                "hiStatus": "ERRORED",
                "description": f"Encryption failed: {exc}",
            })
            continue

        entries.append({
            "content": encrypted_content,
            "media": "application/fhir+json",
            "checksum": _compute_checksum(encrypted_content),
            "careContextReference": care_context_reference,
        })

    if entries:

        # Our own public key must be sent in X.509 DER format -- confirmed
        # as the actual root cause of the earlier "ABDM-9999: Could not
        # read encrypted content" 400 error. The INCOMING HIU key stays
        # raw uncompressed (that direction is confirmed correct already);
        # only our OUTBOUND key needed this conversion.
        outbound_key_material = {
            "cryptoAlg": "ECDH",
            "curve": "Curve25519",
            "dhPublicKey": {
                "expiry": generate_expiry_time(minutes=60),
                "parameters": "Curve25519/32byte random key",
                "keyValue": to_x509_public_key(hip_key_material["public_key"]),
            },
            "nonce": hip_key_material["nonce"],
        }

        push_response = send_health_information_data(
            data_push_url=data_push_url,
            transaction_id=transaction_id,
            entries=entries,
            key_material=outbound_key_material,
        )

        log_api_call("Pushing Encrypted Records to HIU", f"POST {data_push_url}", push_response.status_code)

        pushed_ok = push_response.status_code in (200, 202)

        for entry in entries:
            status_responses.append({
                "careContextReference": entry["careContextReference"],
                "hiStatus": "DELIVERED" if pushed_ok else "ERRORED",
                "description": "Transferred successfully" if pushed_ok else f"Push failed with status {push_response.status_code}",
            })

        if not pushed_ok:
            print_api_response(push_response)

    else:
        pushed_ok = False

    session_status = "TRANSFERRED" if (entries and pushed_ok) else "FAILED"

    notify_response = send_health_information_notify(
        consent_id=consent_id,
        transaction_id=transaction_id,
        hip_id=hip_id,
        done_at=generate_safe_past_timestamp(),
        session_status=session_status,
        status_responses=status_responses,
    )

    log_api_call("Notifying ABDM of Transfer Outcome", "POST .../health-information/notify", notify_response.status_code)

    if notify_response.status_code not in (200, 202):
        print_api_response(notify_response)

    if session_status == "TRANSFERRED":
        log_phase("Records delivered to the HIU successfully")
    else:
        log_error("Records were not successfully delivered to the HIU -- see status responses above")


async def process_health_information_request(
    callback_data,
):

    try:
        log_phase("Data request received -- HIU wants the patient's records (POST /api/v3/hip/health-information/request)")

        headers = callback_data["headers"]
        body = callback_data["body"]

        request_id = headers.get("request-id")
        hip_id = headers.get("x-hip-id")
        transaction_id = body.get("transactionId")

        hi_request = body.get("hiRequest",{})
        consent_id = (hi_request.get("consent", {}).get("id"))
        date_range = hi_request.get("dateRange",{})
        data_push_url = hi_request.get("dataPushUrl")
        key_material = hi_request.get("keyMaterial",{})

        log_phase("Extracted consent ID, approved care contexts, and encryption keys")

        consent = get_consent(consent_id)

        care_context_references = []
        fhir_bundles = None

        if consent is None:
            log_error(f"No stored consent artifact found for consentId={consent_id} -- cannot build records (was it ever GRANTED?).")
        else:
            care_context_references = [
                care_context.get("careContextReference")
                for care_context in consent.get("care_contexts", [])
                if care_context.get("careContextReference")
            ]
            fhir_bundles = build_bundles_for_care_contexts(care_context_references)
            log_phase(f"Assembled {len(fhir_bundles)} FHIR record(s) for the approved care context(s)")

        session_data = {
            "request_id": request_id,
            "transaction_id": transaction_id,
            "hip_id": hip_id,
            "consent_id": consent_id,
            "care_context_references": care_context_references,
            "date_range": date_range,
            "data_push_url": data_push_url,
            "key_material": key_material,

            "body": body,

            "records": None,
            "fhir_bundles": fhir_bundles,
            "encrypted_bundle": None,
            "checksum": None,
            "transfer_status": None,
        }

        save_health_information_session(
            transaction_id,
            session_data,
        )

        response = send_on_health_information_request(
            transaction_id=transaction_id,
            request_id=request_id,
        )

        log_api_call("Acknowledging Data Request to ABDM", "POST .../hip/on-request", response.status_code)

        if response.status_code not in (200, 202):
            print_api_response(response)
            return

        if not fhir_bundles or not data_push_url or not key_material:

            if not fhir_bundles:
                reason = "Could not prepare any FHIR records for the approved care context(s)."
            elif not data_push_url:
                reason = "HIU did not provide a dataPushUrl in the request -- unable to deliver records."
            elif not key_material:
                reason = "HIU did not provide keyMaterial in the request -- unable to encrypt records for delivery."

            # Assumption: an empty status_responses list (e.g. when no consent was
            # found at all, so care_context_references is empty) is accepted by
            # ABDM's schema -- not a confirmed detail.
            status_responses = [
                {"careContextReference": ref, "hiStatus": "ERRORED", "description": reason}
                for ref in care_context_references
            ]

            notify_response = send_health_information_notify(
                consent_id=consent_id,
                transaction_id=transaction_id,
                hip_id=hip_id,
                done_at=generate_safe_past_timestamp(),
                session_status="FAILED",
                status_responses=status_responses,
            )

            log_api_call("Notifying ABDM of Transfer Outcome", "POST .../health-information/notify", notify_response.status_code)

            if notify_response.status_code not in (200, 202):
                print_api_response(notify_response)

            log_error(reason)
            return

        log_waiting("Encrypting and pushing records to the HIU")

        _push_and_notify(
            fhir_bundles=fhir_bundles,
            care_context_references=care_context_references,
            data_push_url=data_push_url,
            hiu_key_material=key_material,
            transaction_id=transaction_id,
            consent_id=consent_id,
            hip_id=hip_id,
        )

    except Exception as exc:
        log_error(f"Health Information Request callback processing failed unexpectedly: {exc}")
        return
