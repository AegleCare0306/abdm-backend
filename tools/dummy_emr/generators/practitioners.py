"""
Practitioner Generator.
"""

import random

from dummy_emr.config import NUMBER_OF_DOCTORS
from dummy_emr.constant import FIRST_NAMES,LAST_NAMES,SPECIALITIES
from dummy_emr.utils import practitioner_reference,random_phone


def generate_practitioners():

    practitioners = []

    for index in range(
        1,
        NUMBER_OF_DOCTORS + 1,
    ):

        first = random.choice(
            FIRST_NAMES
        )

        last = random.choice(
            LAST_NAMES
        )

        practitioners.append(
            {
                "practitioner_reference":
                    practitioner_reference(index),

                "full_name":
                    f"Dr. {first} {last}",

                "speciality":
                    random.choice(
                        SPECIALITIES
                    ),

                "qualification":
                    random.choice(
                        [
                            "MBBS",
                            "MBBS, MD",
                            "MBBS, MS",
                            "MBBS, DNB",
                        ]
                    ),

                "registration_number":
                    f"GMC{100000+index}",

                "registration_system":
                    "Gujarat Medical Council",

                "mobile":
                    random_phone(),

                "email":
                    (
                        f"dr.{first.lower()}."
                        f"{last.lower()}"
                        "@aeglecare.in"
                    ),
            }
        )

    return practitioners