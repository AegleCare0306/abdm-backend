"""
Patient Generator.
"""

import random

from dummy_emr.config import NUMBER_OF_PATIENTS

from dummy_emr.constant import (
    FIRST_NAMES,
    LAST_NAMES,
    BLOOD_GROUPS,
)

from dummy_emr.utils import (
    patient_reference,
    random_phone,
    random_abha_number,
    random_abha_address,
)


def generate_patients():

    patients = []

    for index in range(
        1,
        NUMBER_OF_PATIENTS + 1,
    ):

        first_name = random.choice(FIRST_NAMES)

        last_name = random.choice(LAST_NAMES)

        patients.append(
            {
                "patient_reference":
                    patient_reference(index),

                "abha_address":
                    random_abha_address(
                        first_name,
                        last_name,
                        index,
                    ),

                "abha_number":
                    random_abha_number(),

                "full_name":
                    f"{first_name} {last_name}",

                "gender":
                    random.choice(
                        [
                            "Male",
                            "Female",
                        ]
                    ),

                "date_of_birth":
                    (
                        f"{random.randint(1960,2015):04d}-"
                        f"{random.randint(1,12):02d}-"
                        f"{random.randint(1,28):02d}"
                    ),

                "mobile":
                    random_phone(),

                "email":
                    (
                        f"{first_name.lower()}."
                        f"{last_name.lower()}"
                        "@gmail.com"
                    ),

                "blood_group":
                    random.choice(
                        BLOOD_GROUPS
                    ),
            }
        )

    return patients