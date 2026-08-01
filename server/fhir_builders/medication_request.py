"""
MedicationRequest Resource Builder.
"""

from fhir.resources.R4B.medicationrequest import MedicationRequest
from fhir.resources.R4B.dosage import Dosage
from fhir.resources.R4B.quantity import Quantity
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.meta import Meta
from fhir.resources.R4B.coding import Coding

from server.fhir_builders.datetime_utils import to_fhir_datetime


ABDM_MEDICATION_REQUEST_PROFILE = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/MedicationRequest"
ATC_SYSTEM = "http://www.whocc.no/atc"


def build_medication_request(medication_request_row):
    """
    medication_request_row expected keys (matches medication_requests.csv):
        medication_request_reference, encounter_reference, patient_reference,
        medication_reference, generic_name, brand_name, strength, atc_code,
        dosage_form, route, frequency, duration_days, quantity, status,
        authored_on

    NOTE: this row doesn't carry a practitioner_reference (medication_requests.csv
    doesn't currently join to the prescribing doctor) -- MedicationRequest.requester
    is left unset here. If that's needed later, join against encounters.csv by
    encounter_reference to get practitioner_reference and pass it in.
    """

    medication_text = medication_request_row["generic_name"]
    if medication_request_row.get("strength"):
        medication_text += f" {medication_request_row['strength']}"

    dosage_text = f"{medication_request_row['frequency']} for {medication_request_row['duration_days']} days"

    medication_code_kwargs = {"text": medication_text}
    if medication_request_row.get("atc_code"):
        medication_code_kwargs["coding"] = [
            Coding(system=ATC_SYSTEM, code=medication_request_row["atc_code"])
        ]

    kwargs = {
        "id": medication_request_row["medication_request_reference"],
        "meta": Meta(profile=[ABDM_MEDICATION_REQUEST_PROFILE]),
        "status": medication_request_row["status"],
        "intent": "order",
        "medicationCodeableConcept": CodeableConcept(**medication_code_kwargs),
        "subject": Reference(reference=f"Patient/{medication_request_row['patient_reference']}"),
        "encounter": Reference(reference=f"Encounter/{medication_request_row['encounter_reference']}"),
        "authoredOn": to_fhir_datetime(medication_request_row["authored_on"]),
        "dosageInstruction": [
            Dosage(
                text=dosage_text,
                route=CodeableConcept(text=medication_request_row["route"]),
            )
        ],
    }

    if medication_request_row.get("quantity"):
        kwargs["dispenseRequest"] = {
            "quantity": Quantity(value=float(medication_request_row["quantity"]), unit=medication_request_row["dosage_form"])
        }

    medication_request = MedicationRequest(**kwargs)

    return medication_request.model_dump(mode="json", exclude_none=True)
