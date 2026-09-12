"""
Patient Generator.
"""

from dummy_emr.utils import patient_reference


# Real, ABHA-linked patients used for M2 (HIP-Initiated Linking) testing
# against the real ABDM sandbox. Synthetic patients are never generated --
# M2 can only be tested against patients we can actually log into on the
# sandbox ABHA app, so this is the complete, exhaustive patient list.
#
# Values confirmed directly by the project owner. email/blood_group are
# left blank -- not confirmed, not invented.
FIXED_PATIENTS = [
    {
        "full_name": "Aayush Chordia",
        "mobile": "7904191949",
        "abha_address": "aayushchordia4611@sbx",
        "abha_number": "91-6182-1610-5253",
        "gender": "Male",
        "date_of_birth": "20-10-1997",
        "email": "",
        "blood_group": "",
    },
    {
        "full_name": "Manya Parthiv Shah",
        "mobile": "9898034665",
        "abha_address": "91770048252272@sbx",
        "abha_number": "91-7700-4825-2272",
        "gender": "Female",
        "date_of_birth": "01-12-1999",
        "email": "",
        "blood_group": "",
    },
    {
        "full_name": "Priya Parthiv Shah",
        "mobile": "9898034665",
        "abha_address": "91162304663600@sbx",
        "abha_number": "91-1623-0466-3600",
        "gender": "Female",
        "date_of_birth": "27-02-2005",
        "email": "",
        "blood_group": "",
    },
    {
        "full_name": "Pooja Rameshkumar",
        "mobile": "7904191949",
        "abha_address": "91466530750069@sbx",
        "abha_number": "91-4665-3075-0069",
        "gender": "Female",
        "date_of_birth": "17-10-1998",
        "email": "",
        "blood_group": "",
    },
    {
        "full_name": "Pooja Rameshkumar",
        "mobile": "7904191949",
        "abha_address": "poojaanchaliya@sbx",
        "abha_number": "91-4665-3075-0069",
        "gender": "Female",
        "date_of_birth": "17-10-1998",
        "email": "",
        "blood_group": "",
    },
]


def generate_patients():
    """
    Returns a row dict for every real patient in FIXED_PATIENTS (PAT9001..).
    Callers filter this down to whichever patient(s) were selected this run
    before upserting into patients.csv.
    """

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

    return patients
