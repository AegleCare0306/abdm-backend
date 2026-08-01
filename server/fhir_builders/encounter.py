"""
Encounter Resource Builder.
"""

from fhir.resources.R4B.encounter import Encounter, EncounterParticipant
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.period import Period
from fhir.resources.R4B.meta import Meta

from server.fhir_builders.datetime_utils import to_fhir_datetime


ABDM_ENCOUNTER_PROFILE = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Encounter"
FACILITY_ENCOUNTER_ID_SYSTEM = "https://facility.ndhm.gov.in/encounter"
FACILITY_MRN_SYSTEM = "https://facility.ndhm.gov.in/mrn"
V3_ACT_CODE_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-ActCode"

# encounter_type (from encounters.csv) -> (v3-ActCode code, display)
ENCOUNTER_CLASS_MAP = {
    "OPD": ("AMB", "ambulatory"),
    "IPD": ("IMP", "inpatient encounter"),
    "Emergency": ("EMER", "emergency"),
}

VALID_STATUSES = {
    "planned", "arrived", "triaged", "in-progress", "onleave",
    "finished", "cancelled", "entered-in-error", "unknown",
}


def build_encounter(encounter_row):
    """
    encounter_row expected keys (matches encounters.csv):
        encounter_reference, facility_encounter_number, hip_id,
        patient_reference, practitioner_reference, mr_number,
        encounter_datetime, encounter_type, visit_reason, chief_complaint,
        encounter_status, department_reference, clinical_case
    """

    class_code, class_display = ENCOUNTER_CLASS_MAP.get(
        encounter_row["encounter_type"], ("AMB", "ambulatory")
    )

    status = encounter_row["encounter_status"]
    if status not in VALID_STATUSES:
        status = "unknown"

    kwargs = {
        "id": encounter_row["encounter_reference"],
        "meta": Meta(profile=[ABDM_ENCOUNTER_PROFILE]),
        "identifier": [
            Identifier(
                system=FACILITY_ENCOUNTER_ID_SYSTEM,
                value=encounter_row["facility_encounter_number"],
            ),
            Identifier(
                system=FACILITY_MRN_SYSTEM,
                value=encounter_row["mr_number"],
            ),
        ],
        "status": status,
        "class_fhir": Coding(
            system=V3_ACT_CODE_SYSTEM,
            code=class_code,
            display=class_display,
        ),
        "subject": Reference(reference=f"Patient/{encounter_row['patient_reference']}"),
        "participant": [
            EncounterParticipant(
                individual=Reference(
                    reference=f"Practitioner/{encounter_row['practitioner_reference']}"
                )
            )
        ],
        "serviceProvider": Reference(reference=f"Organization/{encounter_row['hip_id']}"),
        "period": Period(start=to_fhir_datetime(encounter_row["encounter_datetime"])),
    }

    if encounter_row.get("chief_complaint"):
        kwargs["reasonCode"] = [CodeableConcept(text=encounter_row["chief_complaint"])]

    encounter = Encounter(**kwargs)

    return encounter.model_dump(mode="json", exclude_none=True)
