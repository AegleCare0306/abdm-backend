"""
Diagnostic Report Generator.
"""

import random

from dummy_emr.case_library import CLINICAL_CASES
from dummy_emr.master_data.diagnoses import DIAGNOSES
from dummy_emr.master_data.lab_tests import LAB_TESTS
from dummy_emr.utils import diagnostic_report_reference


INFECTION_KEYWORDS = (
    "fever", "pneumonia", "bronchitis", "tuberculosis", "appendicitis",
    "tonsillitis", "sinusitis", "pharyngitis", "otitis", "typhoid", "dengue",
)

DIABETIC_KEYWORDS = (
    "diabetes", "metabolic syndrome", "neuropathy",
)

LIPID_RISK_KEYWORDS = (
    "hyperlipidemia", "ischemic heart", "angina", "heart failure",
    "hypertensive heart", "metabolic syndrome", "obesity",
)

RENAL_KEYWORDS = (
    "renal calculus", "hematuria",
)

HEPATOBILIARY_KEYWORDS = (
    "cholelithiasis", "hypothyroid",
)

UTI_KEYWORDS = (
    "urinary tract infection", "hematuria", "renal calculus",
)


def _matches(name, keywords):
    lowered = name.lower()
    return any(keyword in lowered for keyword in keywords)


def _generate_result(lab, diagnosis_name):

    ref = lab["lab_reference"]
    name = diagnosis_name.lower()

    if ref == "LAB000001":  # Complete Blood Count (reported as WBC count)
        if _matches(diagnosis_name, INFECTION_KEYWORDS):
            return str(random.randint(11000, 18000)), "4000-11000", "cells/cumm", "High"
        return str(random.randint(4500, 10500)), "4000-11000", "cells/cumm", "Normal"

    if ref == "LAB000002":  # HbA1c
        if "prediabetes" in name:
            return f"{random.uniform(5.7, 6.4):.1f}", "4.0-5.6", "%", "Borderline"
        if _matches(diagnosis_name, DIABETIC_KEYWORDS):
            return f"{random.uniform(7.0, 9.5):.1f}", "4.0-5.6", "%", "High"
        return f"{random.uniform(4.8, 5.6):.1f}", "4.0-5.6", "%", "Normal"

    if ref == "LAB000003":  # Kidney Function Test (reported as creatinine)
        if _matches(diagnosis_name, RENAL_KEYWORDS):
            return f"{random.uniform(1.3, 2.6):.1f}", "0.6-1.2", "mg/dL", "High"
        return f"{random.uniform(0.6, 1.2):.1f}", "0.6-1.2", "mg/dL", "Normal"

    if ref == "LAB000004":  # Liver Function Test (reported as ALT)
        if _matches(diagnosis_name, HEPATOBILIARY_KEYWORDS):
            return str(random.randint(45, 120)), "7-40", "U/L", "High"
        return str(random.randint(10, 40)), "7-40", "U/L", "Normal"

    if ref == "LAB000005":  # Lipid Profile (reported as total cholesterol)
        if _matches(diagnosis_name, LIPID_RISK_KEYWORDS):
            return str(random.randint(220, 290)), "<200", "mg/dL", "High"
        return str(random.randint(150, 199)), "<200", "mg/dL", "Normal"

    if ref == "LAB000006":  # Blood Glucose (fasting)
        if "prediabetes" in name:
            return str(random.randint(110, 125)), "70-110", "mg/dL", "Borderline"
        if _matches(diagnosis_name, DIABETIC_KEYWORDS):
            return str(random.randint(140, 260)), "70-110", "mg/dL", "High"
        return str(random.randint(80, 110)), "70-110", "mg/dL", "Normal"

    if ref == "LAB000007":  # Dengue NS1
        if "dengue" in name:
            return "Positive", "Negative", "", "Positive"
        return "Negative", "Negative", "", "Normal"

    if ref == "LAB000008":  # Urine Routine
        if _matches(diagnosis_name, UTI_KEYWORDS):
            return "Pus cells 15-20/hpf, leukocyte esterase positive", "No pus cells seen", "", "Abnormal"
        return "No abnormality detected", "No abnormality detected", "", "Normal"

    return "", "", "", ""


def generate_diagnostic_reports(
    encounters,
    start_index=1,
):

    diagnostic_reports = []

    case_lookup = {
        case["case_id"]: case
        for case in CLINICAL_CASES
    }

    diagnosis_lookup = {
        diagnosis["diagnosis_reference"]: diagnosis
        for diagnosis in DIAGNOSES
    }

    lab_lookup = {
        lab["lab_reference"]: lab
        for lab in LAB_TESTS
    }

    report_counter = start_index

    for encounter in encounters:

        case = case_lookup[encounter["clinical_case"]]

        if not case["lab_references"]:
            continue

        diagnosis = diagnosis_lookup[case["diagnosis_reference"]]

        for lab_ref in case["lab_references"]:

            lab = lab_lookup[lab_ref]

            result_value, reference_range, unit, interpretation = _generate_result(
                lab,
                diagnosis["condition_name"],
            )

            diagnostic_reports.append(
                {
                    "diagnostic_report_reference": diagnostic_report_reference(report_counter),
                    "encounter_reference": encounter["encounter_reference"],
                    "patient_reference": encounter["patient_reference"],
                    "lab_reference": lab_ref,
                    "test_name": lab["name"],
                    "loinc": lab["loinc"],
                    "category": lab["category"],
                    "result_value": result_value,
                    "reference_range": reference_range,
                    "unit": unit,
                    "interpretation": interpretation,
                    "status": "final",
                    "issued_datetime": encounter["encounter_datetime"],
                }
            )

            report_counter += 1

    return diagnostic_reports
