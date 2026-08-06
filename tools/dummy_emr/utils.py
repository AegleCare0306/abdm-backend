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


def patient_reference(index):

    return f"PAT{index:04d}"


def practitioner_reference(index):

    return f"DOC{index:04d}"


def organization_reference(index):

    return f"ORG{index:04d}"


def patient_number_suffix(patient_reference):
    """"PAT9001" -> "9001". Used to build identity-derived IDs."""

    return patient_reference[3:]


def new_encounter_reference(
    patient_reference,
    facility_prefix,
    slot,
):
    """
    Identity-derived encounter_reference for encounters created after the
    ENC0001-ENC0012 frozen block, e.g. new_encounter_reference("PAT9001",
    "AHC", 3) -> "ENC9001AHC03" (PAT9001's 3rd new encounter at Aayush
    Health Care). Never overlaps the frozen ENC000N block, and the same
    (patient, facility, slot) always means the same thing forever -- slot
    must be the next unused value for that (patient, facility) pair, read
    from existing data, never a fresh in-memory counter.
    """

    return (
        f"ENC{patient_number_suffix(patient_reference)}"
        f"{facility_prefix}{slot:02d}"
    )


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

















