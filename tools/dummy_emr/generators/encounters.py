"""
Encounter Generator.

Only ever generates NEW encounters (for a real, ABHA-linked patient closing
an HI-type coverage gap, or topping up an already-fully-covered patient).
The frozen ENC0001-ENC0012 block is never produced here -- it's upserted
verbatim from dummy_emr.frozen_data by the caller.
"""

import random
from datetime import datetime, timedelta

from dummy_emr.utils import new_encounter_reference, facility_encounter_number, mr_number, patient_number_suffix
from dummy_emr.csv_writer import max_numeric_suffix
from dummy_emr.case_library import CLINICAL_CASES
from dummy_emr.hi_types import hi_types_for_case, ALL_HI_TYPES
import re


# Together, these four cases' HI types union to exactly the 8 ABDM HI
# types (see dummy_emr.hi_types.ALL_HI_TYPES):
#   CASE001 Essential Hypertension      -> OPConsultation, Prescription, Invoice
#   CASE020 Pulmonary Tuberculosis      -> OPConsultation, Prescription, DiagnosticReport, HealthDocumentRecord
#   CASE030 Distal Radius Fracture      -> OPConsultation, Prescription, DischargeSummary
#   CASE040 Routine Immunization Visit  -> OPConsultation, WellnessRecord, ImmunizationRecord
# Tried in this order, skipping any case that would add nothing new, so a
# facility that already has partial coverage (e.g. from a frozen encounter)
# only gets the cases it's actually still missing.
COVERAGE_CASE_ORDER = ["CASE001", "CASE020", "CASE030", "CASE040"]


def build_practitioner_map(practitioner_organizations):

    practitioner_map = {}

    for row in practitioner_organizations:

        practitioner_map.setdefault(
            row["hip_id"],
            [],
        ).append(
            row["practitioner_reference"]
        )

    return practitioner_map


def _facility_sequence_pattern(prefix):
    return re.compile(rf"^{re.escape(prefix)}-\d{{4}}-(\d{{6}})$")


def _mr_sequence_pattern(prefix):
    return re.compile(rf"^MR-{re.escape(prefix)}-(\d{{6}})$")


def _slot_pattern(patient_reference, facility_prefix):
    suffix = patient_number_suffix(patient_reference)
    return re.compile(rf"^ENC{re.escape(suffix)}{re.escape(facility_prefix)}(\d{{2}})$")


def build_facility_counters(all_encounters, hips):
    """
    facility_encounter_number and mr_number are facility-wide running
    counters shared across every patient at that facility (confirmed by
    the frozen data: PAT9001's MR-AHC-000001/000002 are immediately
    followed by PAT9003's MR-AHC-000003/000004) -- NOT per-patient. Reads
    the max sequence already used at each facility, across every encounter
    on file (any patient), so a new encounter's number always continues
    forward and never collides with anything already assigned.

    Returns (visit_counters, mr_counters), each {hip_id: next_sequence}.
    """

    visit_counters = {}
    mr_counters = {}

    for hip in hips:

        hip_id = hip["hip_id"]
        prefix = hip["prefix"]

        fe_values = [r["facility_encounter_number"] for r in all_encounters if r["hip_id"] == hip_id]
        mr_values = [r["mr_number"] for r in all_encounters if r["hip_id"] == hip_id]

        visit_counters[hip_id] = max_numeric_suffix(fe_values, _facility_sequence_pattern(prefix)) + 1
        mr_counters[hip_id] = max_numeric_suffix(mr_values, _mr_sequence_pattern(prefix)) + 1

    return visit_counters, mr_counters


def build_slot_counters(patient_reference, patient_encounters, hips):
    """
    The new-scheme encounter_reference slot IS per (patient, facility).
    Returns {hip_id: next_slot} for this one patient, derived from the
    highest slot already used in patient_encounters (this patient's rows
    only) at each facility.
    """

    slot_counters = {}

    for hip in hips:

        hip_id = hip["hip_id"]
        prefix = hip["prefix"]

        pattern = _slot_pattern(patient_reference, prefix)
        values = [r["encounter_reference"] for r in patient_encounters if r["hip_id"] == hip_id]

        slot_counters[hip_id] = max_numeric_suffix(values, pattern) + 1

    return slot_counters


def _new_encounter_row(
    patient,
    hip,
    case,
    practitioner_map,
    visit_counters,
    mr_counters,
    slot_counters,
):

    hip_id = hip["hip_id"]
    prefix = hip["prefix"]

    encounter_time = (
        datetime.now()
        - timedelta(
            days=random.randint(0, 365),
            hours=random.randint(0, 12),
        )
    )

    doctor = random.choice(practitioner_map[hip_id])

    slot = slot_counters[hip_id]
    slot_counters[hip_id] += 1

    visit_seq = visit_counters[hip_id]
    visit_counters[hip_id] += 1

    mr_seq = mr_counters[hip_id]
    mr_counters[hip_id] += 1

    return {
        "encounter_reference": new_encounter_reference(patient["patient_reference"], prefix, slot),
        "facility_encounter_number": facility_encounter_number(prefix, encounter_time.year, visit_seq),
        "hip_id": hip_id,
        "patient_reference": patient["patient_reference"],
        "practitioner_reference": doctor,
        "mr_number": mr_number(prefix, mr_seq),
        "encounter_datetime": encounter_time.strftime("%Y-%m-%d %H:%M:%S"),
        "encounter_type": case["encounter"]["type"],
        "visit_reason": case["encounter"]["visit_reason"],
        "chief_complaint": case["encounter"]["chief_complaint"],
        "encounter_status": "finished",
        "department_reference": case["department_reference"],
        "clinical_case": case["case_id"],
    }


def generate_gap_closing_encounters(
    patient,
    existing_patient_encounters,
    hips,
    case_lookup,
    practitioner_map,
    visit_counters,
    mr_counters,
    slot_counters,
):
    """
    For each of the 4 facilities, computes which of the 8 ABDM HI types
    existing_patient_encounters (frozen + previously-added) already cover
    there, then generates just enough new encounters (from
    COVERAGE_CASE_ORDER) to close whatever's still missing. A facility
    that's already fully covered gets no new encounters this call.

    Returns (new_encounters, coverage_log); coverage_log is a list of
    (hip_id, case_id, newly_added_hi_types) for the change report.
    """

    new_encounters = []
    coverage_log = []

    encounters_by_hip = {}
    for row in existing_patient_encounters:
        encounters_by_hip.setdefault(row["hip_id"], []).append(row)

    for hip in hips:

        hip_id = hip["hip_id"]

        covered = set()
        for row in encounters_by_hip.get(hip_id, []):
            covered |= hi_types_for_case(case_lookup[row["clinical_case"]])

        for case_id in COVERAGE_CASE_ORDER:

            if covered >= ALL_HI_TYPES:
                break

            case = case_lookup[case_id]
            added = hi_types_for_case(case) - covered

            if not added:
                continue

            new_row = _new_encounter_row(
                patient, hip, case, practitioner_map,
                visit_counters, mr_counters, slot_counters,
            )
            new_encounters.append(new_row)
            coverage_log.append((hip_id, case_id, sorted(added)))
            covered |= hi_types_for_case(case)

    return new_encounters, coverage_log


def generate_topup_encounters(
    patient,
    count,
    hips,
    practitioner_map,
    visit_counters,
    mr_counters,
    slot_counters,
):
    """
    Adds `count` more encounters for a patient who already has full
    4-facility x 8-HI-type coverage. Facility and case are picked randomly
    (weighted by selection_weight) -- safe because these encounters were
    never previously linked anywhere, and their IDs always move forward.
    """

    new_encounters = []

    for _ in range(count):

        hip = random.choice(hips)
        case = random.choices(
            CLINICAL_CASES,
            weights=[c["selection_weight"] for c in CLINICAL_CASES],
            k=1,
        )[0]

        new_encounters.append(
            _new_encounter_row(
                patient, hip, case, practitioner_map,
                visit_counters, mr_counters, slot_counters,
            )
        )

    return new_encounters
