"""
Procedure Generator.
"""

from dummy_emr.case_library import CLINICAL_CASES
from dummy_emr.master_data.procedures import PROCEDURES
from dummy_emr.utils import procedure_reference


def generate_procedures(
    encounters,
):

    procedures = []

    case_lookup = {
        case["case_id"]: case
        for case in CLINICAL_CASES
    }

    procedure_lookup = {
        procedure["procedure_reference"]: procedure
        for procedure in PROCEDURES
    }

    procedure_counter = 1

    for encounter in encounters:

        case = case_lookup[encounter["clinical_case"]]

        if not case["procedure_references"]:
            continue

        for proc_ref in case["procedure_references"]:

            procedure_master = procedure_lookup[proc_ref]

            procedures.append(
                {
                    "procedure_reference": procedure_reference(procedure_counter),
                    "encounter_reference": encounter["encounter_reference"],
                    "patient_reference": encounter["patient_reference"],
                    "procedure_master_reference": proc_ref,
                    "name": procedure_master["name"],
                    "status": "completed",
                    "outcome": "Successful",
                    "performed_datetime": encounter["encounter_datetime"],
                }
            )

            procedure_counter += 1

    return procedures
