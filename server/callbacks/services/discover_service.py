import asyncio

from server.callbacks.repository.patient_repository import search_patient
from server.callbacks.transformers.patient_transformer import build_patient_payload
from server.linking import send_on_discover
from server.utils import print_api_response
from server.callbacks.repository.patient_identity_repository import save_patient_identity
from server.callbacks.utils.flow_logger import log_phase, log_api_call, log_waiting, log_error

async def process_discover(callback_data):

    try:
        log_phase("Patient search request received from ABDM (POST /api/v3/hip/patient/care-context/discover)")

        headers = callback_data["headers"]
        body = callback_data["body"]

        # MALFORMED-BODY GUARDS (edge-case-review pass, tracker cases
        # M2-25/M2-26): the OLD code took `body["patient"]` on faith
        # (direct key access, not .get()) and then assumed every entry
        # in verifiedIdentifiers/unverifiedIdentifiers was a dict. A
        # missing/null "patient" field, or an identifier list containing
        # non-dict entries, raised a KeyError/AttributeError that WAS
        # caught by this function's own outer try/except -- but only
        # AFTER nothing useful happened and BEFORE send_on_discover() (the
        # ABDM ack) was ever reached, so ABDM got no response at all, just
        # a silent timeout, same failure shape as M2-16's stored-consent
        # guard. Normalizing defensively here lets processing continue far
        # enough to still send ABDM a proper "no match" acknowledgment.
        patient = body.get("patient")
        if not isinstance(patient, dict):
            if patient is not None:
                log_error(f"Discover request's 'patient' field was not an object (got {type(patient).__name__}) -- treating as no identifiers rather than crashing.")
            patient = {}

        verified = patient.get("verifiedIdentifiers") or []
        if not isinstance(verified, list):
            log_error(f"Discover request's 'verifiedIdentifiers' was not a list (got {type(verified).__name__}) -- treating as empty rather than crashing.")
            verified = []

        unverified = patient.get("unverifiedIdentifiers") or []
        if not isinstance(unverified, list):
            log_error(f"Discover request's 'unverifiedIdentifiers' was not a list (got {type(unverified).__name__}) -- treating as empty rather than crashing.")
            unverified = []

        hip_id = headers.get("x-hip-id")
        abha_address = None
        abha_number = None
        mobile = None
        mr_number = None

        for identifier in verified:

            if not isinstance(identifier, dict):
                continue

            if identifier.get("type") == "MOBILE":
                mobile = identifier.get("value")

            if identifier.get("type") == "ABHA_NUMBER":
                abha_number = identifier.get("value")

            if identifier.get("type") == "abhaAddress":
                abha_address = identifier.get("value")

        for identifier in unverified:

            if not isinstance(identifier, dict):
                continue

            if identifier.get("type") == "MR":
                mr_number = identifier.get("value")

        log_phase("Extracted patient identifiers (ABHA address, mobile, MR if provided)")

        name = patient.get("name")
        gender = patient.get("gender")
        year_of_birth = patient.get("yearOfBirth")

        patient_profile= {
            "abha_address": abha_address,
            "abha_number": abha_number,
            "mobile": mobile,
            "name": name,
            "year_of_birth": year_of_birth,
            "hip_id": hip_id,
        }

        save_patient_identity(
            abha_address,
            patient_profile,
        )

        transaction_id = body.get("transactionId")
        request_id = headers.get("request-id")

        patient_data = search_patient(
        abha_address=abha_address,
        hip_id=hip_id,
        )
        patient_payload = build_patient_payload(patient_data)

        if patient_data:
            log_phase(f"Found {len(patient_data)} matching record(s)")
        else:
            log_phase("No matching records found")

        # Runs the blocking requests.post() chain (and its internal
        # get_gateway_token() call) on a worker thread -- this server runs
        # both the M2 HIP and M3 HIU roles in one event loop, so a
        # synchronous call sitting directly in an async def callback
        # handler would block that loop for every other in-flight request
        # for however long the call takes.
        response = await asyncio.to_thread(
            send_on_discover,
            transaction_id,
            request_id,
            patient_payload,
        )

        log_api_call("Reporting Patient Match to ABDM", "POST .../on-discover", response.status_code)

        if response.status_code != 202:
            print_api_response(response)
            return

        log_waiting("Waiting for the patient to choose to link these records in the PHR app")

    except Exception as exc:
        log_error(f"Discover callback processing failed unexpectedly: {exc}")
        return
