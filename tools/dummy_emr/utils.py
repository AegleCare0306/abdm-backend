"""
Shared utility functions.
"""

import random
import string


def random_phone():

    return (
        "9"
        + "".join(
            random.choices(
                string.digits,
                k=9,
            )
        )
    )


def random_abha_number():

    return (
        f"{random.randint(10,99)}-"
        f"{random.randint(1000,9999)}-"
        f"{random.randint(1000,9999)}-"
        f"{random.randint(1000,9999)}"
    )


def random_abha_address(first_name, last_name, index):

    return (
        f"{first_name.lower()}"
        f"{last_name.lower()}"
        f"{index}@sbx"
    )


def patient_reference(index):

    return f"PAT{index:04d}"


def practitioner_reference(index):

    return f"DOC{index:04d}"


def organization_reference(index):

    return f"ORG{index:04d}"


def encounter_reference(index):

    return f"ENC{index:04d}"


def condition_reference(index):

    return f"CON{index:04d}"


def medication_reference(index):

    return f"MED{index:04d}"


def medication_request_reference(index):

    return f"MRQ{index:04d}"


def diagnostic_report_reference(index):

    return f"DRP{index:04d}"


def observation_reference(index):

    return f"OBS{index:04d}"


def procedure_reference(index):

    return f"PRO{index:04d}"


def immunization_reference(index):

    return f"IMM{index:04d}"


def document_reference(index):

    return f"DOCREF{index:04d}"


def wellness_reference(index):

    return f"WELL{index:04d}"


def invoice_reference(index):

    return f"INV{index:04d}"


def care_context_reference(index):

    return f"CC{index:06d}"

def facility_encounter_number(
    hip_prefix,
    year,
    sequence,
):

    return (
        f"{hip_prefix}-{year}-{sequence:06d}"
    )


def mr_number(
    hip_prefix,
    sequence,
):

    return (
        f"MR-{hip_prefix}-{sequence:06d}"
    )

















