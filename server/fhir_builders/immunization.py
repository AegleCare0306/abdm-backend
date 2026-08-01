"""
Immunization Resource Builder.
"""

from fhir.resources.R4B.immunization import Immunization
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.meta import Meta

from server.fhir_builders.datetime_utils import to_fhir_datetime


ABDM_IMMUNIZATION_PROFILE = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Immunization"


def build_immunization(immunization_row):
    """
    immunization_row expected keys (matches immunizations.csv):
        immunization_reference, encounter_reference, patient_reference,
        vaccine_reference, vaccine_name, status, occurrence_datetime
    """

    kwargs = {
        "id": immunization_row["immunization_reference"],
        "meta": Meta(profile=[ABDM_IMMUNIZATION_PROFILE]),
        "status": immunization_row["status"],
        "vaccineCode": CodeableConcept(text=immunization_row["vaccine_name"]),
        "patient": Reference(reference=f"Patient/{immunization_row['patient_reference']}"),
        "encounter": Reference(reference=f"Encounter/{immunization_row['encounter_reference']}"),
        "occurrenceDateTime": to_fhir_datetime(immunization_row["occurrence_datetime"]),
    }

    immunization = Immunization(**kwargs)

    return immunization.model_dump(mode="json", exclude_none=True)
