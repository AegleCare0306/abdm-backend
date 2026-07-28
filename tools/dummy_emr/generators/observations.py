"""
Observation Generator.
"""

import random
from datetime import datetime

from dummy_emr.case_library import CLINICAL_CASES
from dummy_emr.master_data.diagnoses import DIAGNOSES
from dummy_emr.master_data.observation_catalog import OBSERVATIONS
from dummy_emr.utils import observation_reference


FEVER_KEYWORDS = (
    "fever", "dengue", "typhoid", "pneumonia", "bronchitis",
    "tuberculosis", "appendicitis", "heat stroke", "otitis",
    "tonsillitis", "sinusitis", "pharyngitis", "diarrhea",
)

HYPERTENSIVE_KEYWORDS = (
    "hypertension", "hypertensive", "angina", "ischemic heart",
    "heart failure", "heart disease",
)

DIABETIC_KEYWORDS = (
    "diabetes", "metabolic syndrome", "prediabetes", "neuropathy",
)

RESPIRATORY_DISTRESS_KEYWORDS = (
    "pneumonia", "heart failure", "asthma", "copd", "chest pain",
    "heat stroke", "road traffic accident",
)

TACHYCARDIA_KEYWORDS = (
    "atrial fibrillation", "panic disorder", "heart failure", "anxiety",
) + FEVER_KEYWORDS


def _matches(name, keywords):
    lowered = name.lower()
    return any(keyword in lowered for keyword in keywords)


def _patient_age(date_of_birth, encounter_datetime):

    if not date_of_birth:
        return 35  # unknown DOB (real patient not yet profiled) -> assume adult

    birth_year = int(date_of_birth[:4])
    encounter_year = int(encounter_datetime[:4])
    return max(encounter_year - birth_year, 0)


def _generate_value(obs_master, diagnosis_name, department_reference, age):

    ref = obs_master["observation_reference"]
    fever = _matches(diagnosis_name, FEVER_KEYWORDS)
    hypertensive = _matches(diagnosis_name, HYPERTENSIVE_KEYWORDS)
    diabetic = _matches(diagnosis_name, DIABETIC_KEYWORDS)
    resp_distress = _matches(diagnosis_name, RESPIRATORY_DISTRESS_KEYWORDS) or department_reference == "DEP003"
    tachycardic = _matches(diagnosis_name, TACHYCARDIA_KEYWORDS)
    pediatric = age < 18

    if ref == "OBS000001":  # Blood Pressure
        if hypertensive:
            systolic = random.randint(140, 170)
            diastolic = random.randint(90, 105)
        else:
            systolic = random.randint(108, 128)
            diastolic = random.randint(68, 84)
        return f"{systolic}/{diastolic}"

    if ref == "OBS000002":  # Heart Rate
        if tachycardic:
            return str(random.randint(100, 130))
        return str(random.randint(65, 95))

    if ref == "OBS000003":  # Respiratory Rate
        if resp_distress:
            return str(random.randint(22, 32))
        return str(random.randint(14, 20))

    if ref == "OBS000004":  # Body Temperature
        if fever:
            return f"{random.uniform(38.0, 40.0):.1f}"
        return f"{random.uniform(36.5, 37.2):.1f}"

    if ref == "OBS000005":  # Weight
        if pediatric:
            return str(round(random.uniform(10, 45), 1))
        return str(round(random.uniform(50, 90), 1))

    if ref == "OBS000006":  # Height
        if pediatric:
            return str(round(random.uniform(70, 150), 1))
        return str(round(random.uniform(150, 185), 1))

    if ref == "OBS000007":  # Blood Glucose
        if diabetic:
            return str(random.randint(160, 280))
        return str(random.randint(80, 110))

    if ref == "OBS000008":  # Oxygen Saturation
        if resp_distress:
            return str(random.randint(88, 94))
        return str(random.randint(96, 99))

    return ""


def generate_observations(
    encounters,
    patients,
):

    observations = []

    case_lookup = {
        case["case_id"]: case
        for case in CLINICAL_CASES
    }

    diagnosis_lookup = {
        diagnosis["diagnosis_reference"]: diagnosis
        for diagnosis in DIAGNOSES
    }

    obs_master_lookup = {
        obs["observation_reference"]: obs
        for obs in OBSERVATIONS
    }

    patient_lookup = {
        patient["patient_reference"]: patient
        for patient in patients
    }

    obs_counter = 1

    for encounter in encounters:

        case = case_lookup[encounter["clinical_case"]]

        if not case["observation_references"]:
            continue

        diagnosis = diagnosis_lookup[case["diagnosis_reference"]]
        patient = patient_lookup[encounter["patient_reference"]]

        age = _patient_age(
            patient["date_of_birth"],
            encounter["encounter_datetime"],
        )

        for obs_ref in case["observation_references"]:

            obs_master = obs_master_lookup[obs_ref]

            value = _generate_value(
                obs_master,
                diagnosis["condition_name"],
                case["department_reference"],
                age,
            )

            observations.append(
                {
                    "observation_reference": observation_reference(obs_counter),
                    "encounter_reference": encounter["encounter_reference"],
                    "patient_reference": encounter["patient_reference"],
                    "observation_master_reference": obs_ref,
                    "name": obs_master["name"],
                    "loinc": obs_master["loinc"],
                    "value": value,
                    "unit": obs_master["unit"],
                    "effective_datetime": encounter["encounter_datetime"],
                    "status": "final",
                }
            )

            obs_counter += 1

    return observations
