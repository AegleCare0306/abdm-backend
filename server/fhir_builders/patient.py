"""
Patient Resource Builder.
"""

from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.humanname import HumanName
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.contactpoint import ContactPoint
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.meta import Meta


ABDM_PATIENT_PROFILE = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Patient"
ABHA_ID_SYSTEM = "https://healthid.ndhm.gov.in"

# Confirmed against the published NRCeS FHIR IG for ABDM (CodeSystem-ndhm-identifier-type-code):
# https://nrces.in/ndhm/fhir/r4/CodeSystem-ndhm-identifier-type-code.html
IDENTIFIER_TYPE_CODE_SYSTEM = "https://nrces.in/ndhm/fhir/r4/CodeSystem/ndhm-identifier-type-code"
ABHA_TYPE_CODE = "ABHA"
ABHA_TYPE_DISPLAY = "Ayushman Bharat Health Account (ABHA) ID"

GENDER_MAP = {
    "male": "male",
    "female": "female",
    "other": "other",
    "unknown": "unknown",
}


def build_patient(patient_row):
    """
    patient_row expected keys (matches patients.csv):
        patient_reference, abha_address, abha_number, full_name,
        gender, date_of_birth, mobile, email, blood_group

    Any of abha_address, abha_number, gender, date_of_birth, mobile,
    email may be blank (e.g. a real patient not yet fully profiled) --
    those fields are simply omitted from the resource rather than sent
    as empty strings, since FHIR fields don't accept blanks.
    """

    identifiers = []

    if patient_row.get("abha_number"):
        identifiers.append(
            Identifier(
                type=CodeableConcept(
                    coding=[Coding(
                        system=IDENTIFIER_TYPE_CODE_SYSTEM,
                        code=ABHA_TYPE_CODE,
                        display=ABHA_TYPE_DISPLAY,
                    )],
                    text="ABHA Number",
                ),
                system=ABHA_ID_SYSTEM,
                value=patient_row["abha_number"],
            )
        )

    if patient_row.get("abha_address"):
        identifiers.append(
            Identifier(
                type=CodeableConcept(
                    coding=[Coding(
                        system=IDENTIFIER_TYPE_CODE_SYSTEM,
                        code=ABHA_TYPE_CODE,
                        display=ABHA_TYPE_DISPLAY,
                    )],
                    text="ABHA Address",
                ),
                system=ABHA_ID_SYSTEM,
                value=patient_row["abha_address"],
            )
        )

    telecom = []

    if patient_row.get("mobile"):
        telecom.append(ContactPoint(system="phone", value=patient_row["mobile"]))

    if patient_row.get("email"):
        telecom.append(ContactPoint(system="email", value=patient_row["email"]))

    kwargs = {
        "id": patient_row["patient_reference"],
        "meta": Meta(profile=[ABDM_PATIENT_PROFILE]),
        "name": [HumanName(text=patient_row["full_name"])],
    }

    if identifiers:
        kwargs["identifier"] = identifiers

    if telecom:
        kwargs["telecom"] = telecom

    gender_code = GENDER_MAP.get((patient_row.get("gender") or "").strip().lower())
    if gender_code:
        kwargs["gender"] = gender_code

    if patient_row.get("date_of_birth"):
        # CONFIRMED REAL FAILURE (2026-08-04): patients.csv stores
        # date_of_birth as DD-MM-YYYY (e.g. "20-10-1997"), but FHIR's
        # birthDate requires ISO 8601 (YYYY-MM-DD) -- sending the raw
        # CSV value raised a real pydantic validation error building
        # the Patient resource for a Health Information Request
        # ("Date value string does not match spec regex"). Converts
        # DD-MM-YYYY -> YYYY-MM-DD; passes anything already in ISO
        # form (or otherwise unparseable) through unchanged rather
        # than guessing further formats.
        raw_dob = patient_row["date_of_birth"]
        parts = raw_dob.split("-")
        if len(parts) == 3 and len(parts[0]) == 2 and len(parts[2]) == 4:
            day, month, year = parts
            kwargs["birthDate"] = f"{year}-{month}-{day}"
        else:
            kwargs["birthDate"] = raw_dob

    patient = Patient(**kwargs)

    return patient.model_dump(mode="json", exclude_none=True)
