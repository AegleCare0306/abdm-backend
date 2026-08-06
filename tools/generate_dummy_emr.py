"""
Dummy EMR Generator.

Generates data ONLY for the real, ABHA-linked patients in
dummy_emr.generators.patients.FIXED_PATIENTS -- no synthetic patients.
Every run is additive/merge-only: existing rows for encounters/patients not
touched this run are left byte-for-byte untouched (see dummy_emr.csv_writer.
upsert_csv), and the 12 originally-generated encounters (ENC0001-ENC0012,
some already linked in the live ABDM sandbox) are frozen forever in
dummy_emr.frozen_data and only ever upserted verbatim, never recomputed.

Run interactively:
    cd tools
    python generate_dummy_emr.py
"""

from dummy_emr.config import MASTER_OUTPUT_FOLDER, TRANSACTION_OUTPUT_FOLDER, RANDOM_SEED, HIPS
from dummy_emr.csv_writer import write_csv, read_csv, upsert_csv, next_reference_index
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


def process_patient(patient, case_lookup, practitioner_map, coverage_report):
    """
    Ensures this patient's frozen encounters (if any) are upserted, then
    closes any remaining 4-facility x 8-HI-type coverage gap, or -- if
    already fully covered -- prompts for an optional top-up count. Every
    write is a merge/upsert; other patients' rows are never touched.
    """

    patient_ref = patient["patient_reference"]

    frozen_encounters = [row for row in FROZEN_ENCOUNTERS if row["patient_reference"] == patient_ref]
    frozen_observations = [row for row in FROZEN_OBSERVATIONS if row["patient_reference"] == patient_ref]
    frozen_diagnostic_reports = [row for row in FROZEN_DIAGNOSTIC_REPORTS if row["patient_reference"] == patient_ref]

    if frozen_encounters:
        upsert_csv(TRANSACTION_OUTPUT_FOLDER, "encounters.csv", frozen_encounters, ("encounter_reference",))
    if frozen_observations:
        upsert_csv(TRANSACTION_OUTPUT_FOLDER, "observations.csv", frozen_observations, ("observation_reference",))
    if frozen_diagnostic_reports:
        upsert_csv(TRANSACTION_OUTPUT_FOLDER, "diagnostic_reports.csv", frozen_diagnostic_reports, ("diagnostic_report_reference",))

    # Re-read from disk (facility-wide counters need every patient's rows;
    # this patient's own frozen rows, if any, were just (re)written above).
    all_encounters = read_csv(TRANSACTION_OUTPUT_FOLDER, "encounters.csv")
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

    cond_start = next_reference_index(TRANSACTION_OUTPUT_FOLDER, "conditions.csv", "condition_reference", "CON")
    obs_start = next_reference_index(TRANSACTION_OUTPUT_FOLDER, "observations.csv", "observation_reference", "OBS")
    mrq_start = next_reference_index(TRANSACTION_OUTPUT_FOLDER, "medication_requests.csv", "medication_request_reference", "MRQ")
    drp_start = next_reference_index(TRANSACTION_OUTPUT_FOLDER, "diagnostic_reports.csv", "diagnostic_report_reference", "DRP")
    pro_start = next_reference_index(TRANSACTION_OUTPUT_FOLDER, "procedures.csv", "procedure_reference", "PRO")
    docref_start = next_reference_index(TRANSACTION_OUTPUT_FOLDER, "documents.csv", "document_reference", "DOCREF")
    imm_start = next_reference_index(TRANSACTION_OUTPUT_FOLDER, "immunizations.csv", "immunization_reference", "IMM")
    inv_start = next_reference_index(TRANSACTION_OUTPUT_FOLDER, "billing.csv", "invoice_reference", "INV")

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

    upsert_csv(TRANSACTION_OUTPUT_FOLDER, "encounters.csv", new_encounters, ("encounter_reference",))
    upsert_csv(TRANSACTION_OUTPUT_FOLDER, "conditions.csv", new_conditions, ("condition_reference",))
    upsert_csv(TRANSACTION_OUTPUT_FOLDER, "observations.csv", new_observations, ("observation_reference",))
    upsert_csv(TRANSACTION_OUTPUT_FOLDER, "medication_requests.csv", new_medication_requests, ("medication_request_reference",))
    upsert_csv(TRANSACTION_OUTPUT_FOLDER, "diagnostic_reports.csv", new_diagnostic_reports, ("diagnostic_report_reference",))
    upsert_csv(TRANSACTION_OUTPUT_FOLDER, "procedures.csv", new_procedures, ("procedure_reference",))
    upsert_csv(TRANSACTION_OUTPUT_FOLDER, "documents.csv", new_documents, ("document_reference",))
    upsert_csv(TRANSACTION_OUTPUT_FOLDER, "immunizations.csv", new_immunizations, ("immunization_reference",))
    upsert_csv(TRANSACTION_OUTPUT_FOLDER, "billing.csv", new_billing, ("invoice_reference",))

    print(f"      Added {len(new_encounters)} new encounter(s) for {patient['full_name']}.")


def main():

    random.seed(RANDOM_SEED)
    print("\nGenerating Dummy EMR...\n")

    # Deterministic given the fixed seed and this fixed call order (nothing
    # consumes random() before these three), so full-overwrite here always
    # reproduces byte-identical master data regardless of which patients
    # are selected below -- no merge logic needed.
    organizations = generate_organizations()
    practitioners = generate_practitioners()
    practitioner_organizations = generate_practitioner_organizations(practitioners)

    write_csv(MASTER_OUTPUT_FOLDER, "organizations.csv", organizations)
    write_csv(MASTER_OUTPUT_FOLDER, "practitioners.csv", practitioners)
    write_csv(MASTER_OUTPUT_FOLDER, "practitioner_organizations.csv", practitioner_organizations)

    all_patients = generate_patients()
    selected_patients = select_patients(all_patients)

    upsert_csv(MASTER_OUTPUT_FOLDER, "patients.csv", selected_patients, ("patient_reference",))

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
