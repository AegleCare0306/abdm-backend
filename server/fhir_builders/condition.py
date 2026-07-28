"""
Condition Resource Builder.
"""

from fhir.resources.R4B.condition import Condition
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.meta import Meta


ABDM_CONDITION_PROFILE = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Condition"
SNOMED_SYSTEM = "http://snomed.info/sct"
ICD10_SYSTEM = "http://hl7.org/fhir/sid/icd-10"
CLINICAL_STATUS_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-clinical"
VERIFICATION_STATUS_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-ver-status"

# severity text (from diagnoses master) -> SNOMED CT severity code
SEVERITY_SNOMED = {
    "Mild": "255604002",
    "Moderate": "6736007",
    "Severe": "24484000",
}


def build_condition(condition_row):
    """
    condition_row expected keys (matches conditions.csv):
        condition_reference, encounter_reference, patient_reference,
        clinical_case, diagnosis_reference, condition_name, icd10_code,
        snomed_code, chronic, severity, clinical_status,
        verification_status, onset_date, recorded_date
    """

    coding = []
    if condition_row.get("snomed_code"):
        coding.append(
            Coding(
                system=SNOMED_SYSTEM,
                code=condition_row["snomed_code"],
                display=condition_row["condition_name"],
            )
        )
    if condition_row.get("icd10_code"):
        coding.append(
            Coding(
                system=ICD10_SYSTEM,
                code=condition_row["icd10_code"],
            )
        )

    code_kwargs = {"text": condition_row["condition_name"]}
    if coding:
        code_kwargs["coding"] = coding

    kwargs = {
        "id": condition_row["condition_reference"],
        "meta": Meta(profile=[ABDM_CONDITION_PROFILE]),
        "clinicalStatus": CodeableConcept(
            coding=[Coding(system=CLINICAL_STATUS_SYSTEM, code=condition_row["clinical_status"])]
        ),
        "verificationStatus": CodeableConcept(
            coding=[Coding(system=VERIFICATION_STATUS_SYSTEM, code=condition_row["verification_status"])]
        ),
        "code": CodeableConcept(**code_kwargs),
        "subject": Reference(reference=f"Patient/{condition_row['patient_reference']}"),
        "encounter": Reference(reference=f"Encounter/{condition_row['encounter_reference']}"),
    }

    if condition_row.get("onset_date"):
        kwargs["onsetDateTime"] = condition_row["onset_date"]

    if condition_row.get("recorded_date"):
        kwargs["recordedDate"] = condition_row["recorded_date"]

    severity_code = SEVERITY_SNOMED.get(condition_row.get("severity"))
    if severity_code:
        kwargs["severity"] = CodeableConcept(
            coding=[Coding(system=SNOMED_SYSTEM, code=severity_code, display=condition_row["severity"])],
            text=condition_row["severity"],
        )

    condition = Condition(**kwargs)

    return condition.model_dump(mode="json", exclude_none=True)
