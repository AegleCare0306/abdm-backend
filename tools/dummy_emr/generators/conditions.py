"""
Condition Generator.
"""

from dummy_emr.case_library import CLINICAL_CASES
from dummy_emr.master_data.diagnoses import DIAGNOSES
from dummy_emr.utils import condition_reference


def generate_conditions(
    encounters,
    start_index=1,
):

    conditions = []

    case_lookup = {
        case["case_id"]: case
        for case in CLINICAL_CASES
    }

    diagnosis_lookup = {
        diagnosis["diagnosis_reference"]: diagnosis
        for diagnosis in DIAGNOSES
    }

    for index, encounter in enumerate(encounters, start=start_index):

        case = case_lookup[
            encounter["clinical_case"]
        ]

        diagnosis = diagnosis_lookup[
            case["diagnosis_reference"]
        ]

        conditions.append(
            {

                "condition_reference":
                    condition_reference(index),

                "encounter_reference":
                    encounter["encounter_reference"],

                "patient_reference":
                    encounter["patient_reference"],

                "clinical_case":
                    encounter["clinical_case"],

                "diagnosis_reference":
                    diagnosis["diagnosis_reference"],

                "condition_name":
                    diagnosis["condition_name"],

                "icd10_code":
                    diagnosis["icd10"],

                "snomed_code":
                    diagnosis["snomed"],

                "chronic":
                    diagnosis["chronic"],

                "severity":
                    diagnosis["severity"],

                "clinical_status":
                    "active",

                "verification_status":
                    "confirmed",

                "onset_date":
                    encounter["encounter_datetime"][:10],

                "recorded_date":
                    encounter["encounter_datetime"][:10],

            }
        )

    return conditions