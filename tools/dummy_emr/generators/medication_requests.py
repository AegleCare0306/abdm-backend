"""
Medication Request Generator.
"""

from dummy_emr.case_library import CLINICAL_CASES
from dummy_emr.master_data.diagnoses import DIAGNOSES
from dummy_emr.master_data.medications import MEDICATIONS
from dummy_emr.utils import medication_request_reference


ANTIBACTERIAL_ATC_PREFIX = "J0"

FORM_INSTRUCTIONS = {
    "Tablet": ("Twice daily", "Oral", 2),
    "Capsule": ("Twice daily", "Oral", 2),
    "Inhaler": ("As needed (SOS)", "Inhalation", None),
    "Powder": ("As directed after each loose stool", "Oral", None),
    "Cream": ("Apply twice daily", "Topical", 2),
    "Gel": ("Apply twice daily", "Topical", 2),
    "Eye Drops": ("Instill twice daily in the affected eye", "Ophthalmic", 2),
    "Ear Drops": ("Instill twice daily in the affected ear", "Otic", 2),
    "Sachet": ("Once weekly", "Oral", None),
}

ANTIBIOTIC_COURSE_DAYS = 5


def _dosage_instruction(medication, chronic):

    form = medication["dosage_form"]
    atc_code = medication["atc_code"] or ""

    frequency, route, per_day = FORM_INSTRUCTIONS.get(
        form,
        ("As directed", medication["route"], None),
    )

    if form in ("Tablet", "Capsule"):
        if atc_code.startswith(ANTIBACTERIAL_ATC_PREFIX):
            frequency, per_day = "Thrice daily", 3
        elif chronic:
            frequency, per_day = "Once daily", 1

    return frequency, route, per_day


def _duration_days(medication, chronic, follow_up_interval_days):

    atc_code = medication["atc_code"] or ""

    if medication["dosage_form"] in ("Tablet", "Capsule") and atc_code.startswith(ANTIBACTERIAL_ATC_PREFIX):
        return ANTIBIOTIC_COURSE_DAYS

    if chronic:
        return follow_up_interval_days

    return min(follow_up_interval_days, 14)


def generate_medication_requests(
    encounters,
):

    medication_requests = []

    case_lookup = {
        case["case_id"]: case
        for case in CLINICAL_CASES
    }

    diagnosis_lookup = {
        diagnosis["diagnosis_reference"]: diagnosis
        for diagnosis in DIAGNOSES
    }

    medication_lookup = {
        medication["medication_reference"]: medication
        for medication in MEDICATIONS
    }

    request_counter = 1

    for encounter in encounters:

        case = case_lookup[encounter["clinical_case"]]

        if not case["medication_references"]:
            continue

        diagnosis = diagnosis_lookup[case["diagnosis_reference"]]
        chronic = diagnosis["chronic"]

        for med_ref in case["medication_references"]:

            medication = medication_lookup[med_ref]

            frequency, route, per_day = _dosage_instruction(medication, chronic)
            duration_days = _duration_days(medication, chronic, case["follow_up_interval_days"])
            quantity = per_day * duration_days if per_day else ""

            medication_requests.append(
                {
                    "medication_request_reference": medication_request_reference(request_counter),
                    "encounter_reference": encounter["encounter_reference"],
                    "patient_reference": encounter["patient_reference"],
                    "medication_reference": med_ref,
                    "generic_name": medication["generic_name"],
                    "brand_name": medication["brand_name"],
                    "strength": medication["strength"],
                    "atc_code": medication["atc_code"],
                    "dosage_form": medication["dosage_form"],
                    "route": route,
                    "frequency": frequency,
                    "duration_days": duration_days,
                    "quantity": quantity,
                    "status": "active",
                    "authored_on": encounter["encounter_datetime"],
                }
            )

            request_counter += 1

    return medication_requests
