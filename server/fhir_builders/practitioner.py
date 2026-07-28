"""
Practitioner Resource Builder.
"""

from fhir.resources.R4B.practitioner import Practitioner, PractitionerQualification
from fhir.resources.R4B.humanname import HumanName
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.contactpoint import ContactPoint
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.meta import Meta


ABDM_PRACTITIONER_PROFILE = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Practitioner"
PRACTITIONER_ID_SYSTEM = "https://doctor.ndhm.gov.in"


def _split_name(full_name):
    """'Dr. Ramesh Kumar' -> (prefix 'Dr.', given ['Ramesh'], family 'Kumar')"""

    prefix = None
    remainder = full_name

    if full_name.startswith("Dr."):
        prefix = "Dr."
        remainder = full_name[len("Dr."):].strip()

    parts = remainder.split(" ", 1)
    given = [parts[0]] if parts and parts[0] else []
    family = parts[1] if len(parts) > 1 else None

    return prefix, given, family


def build_practitioner(practitioner_row):
    """
    practitioner_row expected keys (matches practitioners.csv):
        practitioner_reference, full_name, speciality, qualification,
        registration_number, registration_system, mobile, email
    """

    prefix, given, family = _split_name(practitioner_row["full_name"])

    name_kwargs = {"text": practitioner_row["full_name"]}
    if given:
        name_kwargs["given"] = given
    if family:
        name_kwargs["family"] = family
    if prefix:
        name_kwargs["prefix"] = [prefix]

    identifiers = [
        Identifier(
            type=CodeableConcept(text=practitioner_row.get("registration_system", "")),
            system=PRACTITIONER_ID_SYSTEM,
            value=practitioner_row["registration_number"],
        )
    ]

    telecom = []
    if practitioner_row.get("mobile"):
        telecom.append(ContactPoint(system="phone", value=practitioner_row["mobile"]))
    if practitioner_row.get("email"):
        telecom.append(ContactPoint(system="email", value=practitioner_row["email"]))

    kwargs = {
        "id": practitioner_row["practitioner_reference"],
        "meta": Meta(profile=[ABDM_PRACTITIONER_PROFILE]),
        "identifier": identifiers,
        "name": [HumanName(**name_kwargs)],
    }

    if telecom:
        kwargs["telecom"] = telecom

    if practitioner_row.get("qualification"):
        kwargs["qualification"] = [
            PractitionerQualification(
                code=CodeableConcept(text=practitioner_row["qualification"])
            )
        ]

    practitioner = Practitioner(**kwargs)

    return practitioner.model_dump(mode="json", exclude_none=True)
