"""
Procedure Resource Builder.
"""

from fhir.resources.R4B.procedure import Procedure
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.meta import Meta

from server.fhir_builders.datetime_utils import to_fhir_datetime


ABDM_PROCEDURE_PROFILE = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Procedure"


def build_procedure(procedure_row):
    """
    procedure_row expected keys (matches procedures.csv):
        procedure_reference, encounter_reference, patient_reference,
        procedure_master_reference, name, status, outcome, performed_datetime
    """

    kwargs = {
        "id": procedure_row["procedure_reference"],
        "meta": Meta(profile=[ABDM_PROCEDURE_PROFILE]),
        "status": procedure_row["status"],
        "code": CodeableConcept(text=procedure_row["name"]),
        "subject": Reference(reference=f"Patient/{procedure_row['patient_reference']}"),
        "encounter": Reference(reference=f"Encounter/{procedure_row['encounter_reference']}"),
        "performedDateTime": to_fhir_datetime(procedure_row["performed_datetime"]),
    }

    if procedure_row.get("outcome"):
        kwargs["outcome"] = CodeableConcept(text=procedure_row["outcome"])

    procedure = Procedure(**kwargs)

    return procedure.model_dump(mode="json", exclude_none=True)
