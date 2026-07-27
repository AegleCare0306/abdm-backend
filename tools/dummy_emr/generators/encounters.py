"""
Encounter Generator.
"""

import random
from datetime import datetime,timedelta

from dummy_emr.config import HIPS
from dummy_emr.utils import encounter_reference,facility_encounter_number,mr_number
from dummy_emr.case_library import CLINICAL_CASES

def generate_encounters(
    patients,
    practitioners,
    practitioner_organizations,
):

    encounters = []

    encounter_counter = 1

    facility_visit_counter = {}
    facility_mr_counter = {}

    practitioner_lookup = {
        practitioner["practitioner_reference"]: practitioner
        for practitioner in practitioners
    }

    practitioner_map = {}

    for row in practitioner_organizations:

        practitioner_map.setdefault(
            row["hip_id"],
            [],
        ).append(
            row["practitioner_reference"]
        )

    for patient in patients:

        visits = random.randint(2,5)

        for _ in range(visits):

            hip = random.choice(HIPS)

            hip_id = hip["hip_id"]

            doctor = random.choice(
                practitioner_map[hip_id]
            )
            case = random.choice(CLINICAL_CASES)
            facility_visit_counter.setdefault(
                hip_id,
                1,
            )

            facility_mr_counter.setdefault(
                hip_id,
                1,
            )

            encounter_time = (
                datetime.now()
                - timedelta(
                    days=random.randint(0,730),
                    hours=random.randint(0,12),
                )
            )

            encounters.append(
                {
                    "encounter_reference": encounter_reference(encounter_counter),
                    "facility_encounter_number": facility_encounter_number(hip["prefix"],encounter_time.year,facility_visit_counter[hip_id],),
                    "hip_id": hip_id,
                    "patient_reference": patient["patient_reference"],
                    "practitioner_reference": doctor,
                    "mr_number": mr_number(hip["prefix"],facility_mr_counter[hip_id],),
                    "encounter_datetime": encounter_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "encounter_type": case["encounter"]["type"],
                    "visit_reason": case["encounter"]["visit_reason"],
                    "chief_complaint": case["encounter"]["chief_complaint"],
                    "encounter_status": "finished",
                    "department": case["encounter"]["department"],
                    "clinical_case": case["case_id"],
                }
            )

            encounter_counter += 1

            facility_visit_counter[hip_id] += 1

            facility_mr_counter[hip_id] += 1

    return encounters