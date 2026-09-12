"""
Dummy EMR Generator.

Generates data ONLY for the real, ABHA-linked patients in
dummy_emr.generators.patients.FIXED_PATIENTS -- no synthetic patients.
Every run is additive/merge-only: existing rows for encounters/patients not
touched this run are left untouched (every write below is an upsert), and
the 12 originally-generated encounters (ENC0001-ENC0012, some already
linked in the live ABDM sandbox) are frozen forever in
dummy_emr.frozen_data and only ever upserted verbatim, never recomputed.

DATA SOURCE: Postgres (server.callbacks.repository.dummy_emr_repository),
not CSV files -- every generator function under dummy_emr/generators/ is
still a pure function returning plain dicts, unchanged by this; only this
orchestrator's own read/write calls changed. patient_records (the
denormalized care-context-discovery table) is populated here too, at
encounter-generation time, in place of the old separate
tools/generate_patient_records.py script.

Run interactively:
    cd tools
    python generate_dummy_emr.py
"""

import sys
from datetime import datetime
from pathlib import Path

# This script is run as `cd tools; python generate_dummy_emr.py`, so
# Python puts tools/ (not the repo root) on sys.path automatically --
# dummy_emr.* resolves fine from there, but server.* needs the repo root
# added explicitly. Same pattern as tools/m3_test_suite/cli.py's own
# sys.path.insert() for the same reason.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from server.config import DATABASE_URL
from server.db import init_engine

# Standalone CLI script, never goes through server/main.py's own startup --
# must initialise repo/'s DB engine itself before any repository import
# below can work. See server/db.py's own docstring. Idempotent.
init_engine(DATABASE_URL)

from server.callbacks.repository import dummy_emr_repository as repository
from server.db_models import (
    Billing, Condition, DiagnosticReport, Document, Immunization,
    MedicationRequest, Observation, Procedure,
)

from dummy_emr.config import RANDOM_SEED, HIPS
from dummy_emr.generators.organizations import generate_organizations
from dummy_emr.generators.practitioners import generate_practitioners
from dummy_emr.generators.patients import generate_patients
from dummy_emr.generators.practitioner_organizations import generate_practitioner_organizations
from dummy_emr.generators.encounters import (
    build_practitioner_map,
    build_facility_counters,
    build_slot_counters,
    generate_gap_closing_encounters,
    generate_topup_encounters,
)
from dummy_emr.generators.conditions import generate_conditions
from dummy_emr.generators.observations import generate_observations
from dummy_emr.generators.medication_requests import generate_medication_requests
from dummy_emr.generators.diagnostic_reports import generate_diagnostic_reports
from dummy_emr.generators.procedures import generate_procedures
from dummy_emr.generators.documents import generate_documents
from dummy_emr.generators.immunizations import generate_immunizations
from dummy_emr.generators.billing import generate_billing
from dummy_emr.case_library import CLINICAL_CASES
from dummy_emr.hi_types import hi_types_for_case
from dummy_emr.frozen_data import FROZEN_ENCOUNTERS, FROZEN_OBSERVATIONS, FROZEN_DIAGNOSTIC_REPORTS


import random


def prompt(label):
    """Prompts for one line of raw input, stripped. Same style as
    tools/m2_test_suite/common.py's prompt()."""
    return input(f"{label}: ").strip()


def select_patients(fixed_patients):
    """
    Numbered list + comma-separated selection or 'all', same interaction
    style as tools/m2_test_suite/common.py's select_patient(). Re-prompts
    on invalid input. Returns the selected patient row dicts.
    """

    print(f"\n{len(fixed_patients)} real patient(s) available:")
    for i, p in enumerate(fixed_patients, start=1):
        print(f"  [{i}] {p['full_name']}  |  {p['abha_address']}")

    while True:
        choice = prompt(
            f"Select patient(s) to generate for (comma-separated, e.g. 1,3) or 'all' (1-{len(fixed_patients)})"
        )
        stripped = choice.strip().lower()
        if stripped == "all":
            return list(fixed_patients)
        parts = [p.strip() for p in choice.split(",") if p.strip()]
        if parts and all(p.isdigit() and 1 <= int(p) <= len(fixed_patients) for p in parts):
            indices = sorted(set(int(p) for p in parts))
            return [fixed_patients[i - 1] for i in indices]
        print("      Invalid choice, try again (e.g. '1,3' or 'all').")


def _upsert_patient_records_for_encounters(encounters, patient, case_lookup):
    """
    One patient_records row per (encounter, hi_type) pair, same
    denormalization tools/generate_patient_records.py used to compute
    separately -- done here instead, at encounter-generation time, so
    patient_records stays in sync with encounters without a second script
    or a runtime dependency from server/ on dummy_emr's own case_library.
    """
    for encounter in encounters:
        case = case_lookup[encounter["clinical_case"]]
        care_context_display = f"{case['name']} - {encounter['encounter_datetime'][:10]}"

        for hi_type in sorted(hi_types_for_case(case)):
            repository.insert_patient_record(
                {
                    "abha_address": patient["abha_address"],
                    "abha_number": patient["abha_number"] or None,
                    "mobile": patient["mobile"] or None,
                    "mr_number": encounter["mr_number"] or None,
                    "facility_id": encounter["hip_id"],
                    "patient_reference": patient["patient_reference"],
                    "name": patient["full_name"],
                    "care_context_reference": encounter["encounter_reference"],
                    "care_context_display": care_context_display,
                    "hi_type": hi_type,
                }
            )


def process_patient(patient, case_lookup, practitioner_map, coverage_report):
    """
    Ensures this patient's frozen encounters (if any) are upserted, then
    closes any remaining 4-facility x 8-HI-type coverage gap, or -- if
    already fully covered -- prompts for an optional top-up count. Every
    write is an upsert; other patients' rows are never touched.
    """

    patient_ref = patient["patient_reference"]

    frozen_encounters = [row for row in FROZEN_ENCOUNTERS if row["patient_reference"] == patient_ref]
    frozen_observations = [row for row in FROZEN_OBSERVATIONS if row["patient_reference"] == patient_ref]
    frozen_diagnostic_reports = [row for row in FROZEN_DIAGNOSTIC_REPORTS if row["patient_reference"] == patient_ref]

    for row in frozen_encounters:
        repository.insert_encounter(row)
    for row in frozen_observations:
        repository.insert_observation(row)
    for row in frozen_diagnostic_reports:
        repository.insert_diagnostic_report(row)

    if frozen_encounters:
        _upsert_patient_records_for_encounters(frozen_encounters, patient, case_lookup)

    # Facility-wide counters need every patient's rows; this patient's own
    # frozen rows, if any, were just (re)upserted above.
    all_encounters = repository.get_all_encounters()
    patient_encounters = [row for row in all_encounters if row["patient_reference"] == patient_ref]

    visit_counters, mr_counters = build_facility_counters(all_encounters, HIPS)
    slot_counters = build_slot_counters(patient_ref, patient_encounters, HIPS)

    new_encounters, coverage_log = generate_gap_closing_encounters(
        patient, patient_encounters, HIPS, case_lookup, practitioner_map,
        visit_counters, mr_counters, slot_counters,
    )

    for hip_id, case_id, added_hi_types in coverage_log:
        coverage_report.append((patient_ref, hip_id, case_id, added_hi_types))

    if not new_encounters:
        answer = prompt(
            f"{patient['full_name']} already has full 4-facility x 8-HI-type coverage. "
            f"How many additional encounters to add? [0]"
        )
        count = int(answer) if answer.isdigit() else 0
        if count > 0:
            new_encounters = generate_topup_encounters(
                patient, count, HIPS, practitioner_map,
                visit_counters, mr_counters, slot_counters,
            )

    if not new_encounters:
        print(f"      No new encounters for {patient['full_name']}.")
        return

    cond_start = repository.next_reference_index(Condition, "condition_reference", "CON")
    obs_start = repository.next_reference_index(Observation, "observation_reference", "OBS")
    mrq_start = repository.next_reference_index(MedicationRequest, "medication_request_reference", "MRQ")
    drp_start = repository.next_reference_index(DiagnosticReport, "diagnostic_report_reference", "DRP")
    pro_start = repository.next_reference_index(Procedure, "procedure_reference", "PRO")
    docref_start = repository.next_reference_index(Document, "document_reference", "DOCREF")
    imm_start = repository.next_reference_index(Immunization, "immunization_reference", "IMM")
    inv_start = repository.next_reference_index(Billing, "invoice_reference", "INV")

    new_conditions = generate_conditions(new_encounters, cond_start)
    new_observations = generate_observations(new_encounters, [patient], obs_start)
    new_medication_requests = generate_medication_requests(new_encounters, mrq_start)
    new_diagnostic_reports = generate_diagnostic_reports(new_encounters, drp_start)
    new_procedures = generate_procedures(new_encounters, pro_start)
    new_documents = generate_documents(new_encounters, docref_start)
    new_immunizations = generate_immunizations(new_encounters, imm_start)
    new_billing = generate_billing(
        new_encounters, new_medication_requests, new_diagnostic_reports, new_procedures, inv_start
    )

    for row in new_encounters:
        repository.insert_encounter(row)
    for row in new_conditions:
        repository.insert_condition(row)
    for row in new_observations:
        repository.insert_observation(row)
    for row in new_medication_requests:
        repository.insert_medication_request(row)
    for row in new_diagnostic_reports:
        repository.insert_diagnostic_report(row)
    for row in new_procedures:
        repository.insert_procedure(row)
    for row in new_documents:
        repository.insert_document(row)
    for row in new_immunizations:
        repository.insert_immunization(row)
    for row in new_billing:
        repository.insert_billing(row)

    _upsert_patient_records_for_encounters(new_encounters, patient, case_lookup)

    print(f"      Added {len(new_encounters)} new encounter(s) for {patient['full_name']}.")


def main():

    random.seed(RANDOM_SEED)
    print("\nGenerating Dummy EMR...\n")

    # Deterministic given the fixed seed and this fixed call order (nothing
    # consumes random() before these three) -- upserted rather than
    # overwritten, since content is identical every run regardless of
    # which patients are selected below.
    organizations = generate_organizations()
    practitioners = generate_practitioners()
    practitioner_organizations = generate_practitioner_organizations(practitioners)

    for row in organizations:
        repository.insert_organization(row)
    for row in practitioners:
        repository.insert_practitioner(row)
    for row in practitioner_organizations:
        repository.insert_practitioner_organization(row)

    all_patients = generate_patients()
    selected_patients = select_patients(all_patients)

    for row in selected_patients:
        patient_row = dict(row)
        # FIXED_PATIENTS stores date_of_birth as "DD-MM-YYYY" text (see
        # dummy_emr/generators/patients.py) -- insert_patient() needs a
        # real date for the Patient.date_of_birth column.
        dob = patient_row.get("date_of_birth")
        patient_row["date_of_birth"] = datetime.strptime(dob, "%d-%m-%Y").date() if dob else None
        repository.insert_patient(patient_row)

    practitioner_map = build_practitioner_map(practitioner_organizations)
    case_lookup = {case["case_id"]: case for case in CLINICAL_CASES}

    coverage_report = []

    for patient in selected_patients:
        print(f"\n--- {patient['full_name']} ({patient['patient_reference']}) ---")
        process_patient(patient, case_lookup, practitioner_map, coverage_report)

    if coverage_report:
        print("\nCoverage-closing encounters generated (patient, facility, case -> new HI type(s)):")
        for patient_ref, hip_id, case_id, added_hi_types in coverage_report:
            case_name = case_lookup[case_id]["name"]
            print(f"  {patient_ref}  {hip_id}  {case_id} ({case_name}) -> {', '.join(added_hi_types)}")

    print("\nGeneration Complete.\n")


if __name__ == "__main__":
    main()
