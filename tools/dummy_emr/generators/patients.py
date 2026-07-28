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


# Real patients needed for actual ABDM sandbox testing (not synthetic data).
# Reserved in the PAT9001+ range so they never collide with the randomly
# generated PAT0001..PATNNNN range above, regardless of NUMBER_OF_PATIENTS.
#
# gender / date_of_birth / blood_group / email are left blank where not
# supplied — these matter for real sandbox registration, so they should be
# filled in with confirmed values rather than guessed.
FIXED_PATIENTS = [
    {
        "full_name": "Aayush Chordia",
        "mobile": "7904191949",
        "abha_address": "aayushchordia1997@sbx",
        "abha_number": "91-6182-1610-5253",
        "gender": "",
        "date_of_birth": "",
        "email": "",
        "blood_group": "",
    },
    {
        "full_name": "Manya Shah",
        "mobile": "9898034665",
        "abha_address": "",
        "abha_number": "",
        "gender": "",
        "date_of_birth": "",
        "email": "",
        "blood_group": "",
    },
    {
        "full_name": "Priya Shah",
        "mobile": "9898034665",
        "abha_address": "",
        "abha_number": "",
        "gender": "",
        "date_of_birth": "",
        "email": "",
        "blood_group": "",
    },
    {
        "full_name": "Pooja Anchaliya",
        "mobile": "7904191949",
        "abha_address": "91466530750069@sbx",
        "abha_number": "91-4665-3075-0069",
        "gender": "",
        "date_of_birth": "",
        "email": "",
        "blood_group": "",
    },
]


def generate_patients():

    patients = []

    for offset, fixed_patient in enumerate(FIXED_PATIENTS, start=1):

        patients.append(
            {
                "patient_reference":
                    patient_reference(9000 + offset),

                "abha_address":
                    fixed_patient["abha_address"],

                "abha_number":
                    fixed_patient["abha_number"],

                "full_name":
                    fixed_patient["full_name"],

                "gender":
                    fixed_patient["gender"],

                "date_of_birth":
                    fixed_patient["date_of_birth"],

                "mobile":
                    fixed_patient["mobile"],

                "email":
                    fixed_patient["email"],

                "blood_group":
                    fixed_patient["blood_group"],
            }
        )

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