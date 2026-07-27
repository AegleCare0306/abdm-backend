"""
Condition Generator.
"""

from dummy_emr.case_library import CLINICAL_CASES
from dummy_emr.utils import condition_reference


def generate_conditions(
    encounters,
):

    conditions = []

    case_lookup = {
        case["case_id"]: case
        for case in CLINICAL_CASES
    }

    for index, encounter in enumerate(encounters, start=1):

        case = case_lookup[
            encounter["clinical_case"]
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

                "condition_name":
                    case["condition"]["name"],

                "icd10_code":
                    case["condition"]["icd10"],

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