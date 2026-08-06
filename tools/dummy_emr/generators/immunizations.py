"""
Immunization Generator.
"""

from dummy_emr.case_library import CLINICAL_CASES
from dummy_emr.master_data.vaccines import VACCINES
from dummy_emr.utils import immunization_reference


def generate_immunizations(
    encounters,
    start_index=1,
):

    immunizations = []

    case_lookup = {
        case["case_id"]: case
        for case in CLINICAL_CASES
    }

    vaccine_lookup = {
        vaccine["vaccine_reference"]: vaccine
        for vaccine in VACCINES
    }

    immunization_counter = start_index

    for encounter in encounters:

        case = case_lookup[encounter["clinical_case"]]

        if not case["vaccine_references"]:
            continue

        for vaccine_ref in case["vaccine_references"]:

            vaccine = vaccine_lookup[vaccine_ref]

            immunizations.append(
                {
                    "immunization_reference": immunization_reference(immunization_counter),
                    "encounter_reference": encounter["encounter_reference"],
                    "patient_reference": encounter["patient_reference"],
                    "vaccine_reference": vaccine_ref,
                    "vaccine_name": vaccine["name"],
                    "status": "completed",
                    "occurrence_datetime": encounter["encounter_datetime"],
                }
            )

            immunization_counter += 1

    return immunizations
