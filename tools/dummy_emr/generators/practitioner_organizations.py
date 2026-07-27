"""
Practitioner Organization Generator.
"""

import random

from dummy_emr.config import HIPS


def generate_practitioner_organizations(
    practitioners,
):

    rows = []

    for practitioner in practitioners:

        assigned = random.sample(
            HIPS,
            random.randint(
                1,
                len(HIPS),
            ),
        )

        for hip in assigned:

            rows.append(
                {
                    "practitioner_reference":
                        practitioner[
                            "practitioner_reference"
                        ],

                    "hip_id":
                        hip["hip_id"],

                    "department":
                        practitioner["speciality"],

                    "designation":
                        "Consultant",

                    "joining_date":
                        "2024-01-01",

                    "active":
                        True,
                }
            )

    return rows