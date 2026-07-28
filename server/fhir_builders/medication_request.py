"""
MedicationRequest Resource Builder.
"""

from fhir.resources.R4B.medicationrequest import MedicationRequest
from fhir.resources.R4B.dosage import Dosage
from fhir.resources.R4B.quantity import Quantity
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.meta import Meta


ABDM_MEDICATION_REQUEST_PROFILE = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/MedicationRequest"


def _to_fhir_datetime(value):
    if not value:
        return None
    return value.replace(" ", "T") + "+05:30"


def build_medication_request(medication_request_row):
    """
    medication_request_row expected keys (matches medication_requests.csv):
        medication_request_reference, encounter_reference, patient_reference,
        medication_reference, generic_name, brand_name, strength,
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

    kwargs = {
        "id": medication_request_row["medication_request_reference"],
        "meta": Meta(profile=[ABDM_MEDICATION_REQUEST_PROFILE]),
        "status": medication_request_row["status"],
        "intent": "order",
        "medicationCodeableConcept": CodeableConcept(text=medication_text),
        "subject": Reference(reference=f"Patient/{medication_request_row['patient_reference']}"),
        "encounter": Reference(reference=f"Encounter/{medication_request_row['encounter_reference']}"),
        "authoredOn": _to_fhir_datetime(medication_request_row["authored_on"]),
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
