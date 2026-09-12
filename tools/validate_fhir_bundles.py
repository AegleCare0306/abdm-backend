"""
validate_fhir_bundles.py

Validates the FHIR resource builders in server/fhir_builders/ against the
real generated CSV data. This is separate from validate_output.py, which
checks the CSVs themselves -- this script checks that the CSVs convert
into structurally valid FHIR R4 resources.

STATUS: this covers the full FHIR phase now -- all 10 resource builders
plus bundle-level structural checks (file count, Composition-first rule,
internal reference resolution). Run generate_fhir_bundles.py before this
script if you want the bundle checks (not just the per-resource ones) to
run against fresh data.

HOW TO RUN
----------
    pip install -r requirements.txt --break-system-packages
    cd tools
    python3 generate_dummy_emr.py       # make sure CSVs exist
    python3 validate_fhir_bundles.py

WHAT "PASS" MEANS HERE
-----------------------
Each row from the relevant master CSV is run through its builder
function. A pass means fhir.resources accepted the constructed resource
without raising a pydantic validation error (i.e. all FHIR-required
fields were present and correctly typed) AND the resulting dict has the
expected resourceType. This is a structural check, not a spec-conformance
check against ABDM's real sandbox validator -- you should still run a
sample of these through ABDM's actual validator before going live.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from server.config import DATABASE_URL
from server.db import init_engine

init_engine(DATABASE_URL)

from server.callbacks.repository import dummy_emr_repository as repository

from server.fhir_builders.patient import build_patient
from server.fhir_builders.practitioner import build_practitioner
from server.fhir_builders.organization import build_organization
from server.fhir_builders.encounter import build_encounter
from server.fhir_builders.condition import build_condition
from server.fhir_builders.observation import build_observation
from server.fhir_builders.medication_request import build_medication_request
from server.fhir_builders.procedure import build_procedure
from server.fhir_builders.diagnostic_report import build_diagnostic_report
from server.fhir_builders.immunization import build_immunization


def run_builder_over_rows(label, rows, build_fn, sample_output_path):
    """
    Runs build_fn(row) for every row and reports pass/fail per row.
    Also writes the FIRST successfully built resource to sample_output_path
    as pretty-printed JSON, so a human can open and read a real example
    rather than just trust the PASS line.
    """

    if not rows:
        print(f"[FAIL] {label}: no rows found -- run generate_dummy_emr.py first")
        return False

    failures = []
    sample_output = None

    for row in rows:
        try:
            result = build_fn(row)
            if result.get("resourceType") is None:
                failures.append((row, "no resourceType in output"))
            elif sample_output is None:
                sample_output = result
        except Exception as exc:
            failures.append((row, f"{type(exc).__name__}: {exc}"))

    if failures:
        bad_row, error = failures[0]
        print(f"[FAIL] {label}: {len(failures)}/{len(rows)} row(s) failed")
        print(f"         -> first failure on {bad_row}: {error}")
        return False

    if sample_output:
        sample_output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(sample_output_path, "w", encoding="utf-8") as f:
            json.dump(sample_output, f, indent=2)

    print(f"[PASS] {label}: all {len(rows)} row(s) built a valid resource")
    if sample_output:
        print(f"         -> full sample written to {sample_output_path}")
    return True


def _extract_references(node, found):
    """Recursively walks a resource dict collecting every 'reference' string value found."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "reference" and isinstance(value, str):
                found.append(value)
            else:
                _extract_references(value, found)
    elif isinstance(node, list):
        for item in node:
            _extract_references(item, found)


def check_bundle_file_count(fhir_output_folder, expected_count):
    """
    WHY: generate_fhir_bundles.py should write exactly one bundle file per
    encounter -- no more, no less. A mismatch usually means either a crash
    partway through, or a bug generating duplicate/skipped encounters.
    """
    if not fhir_output_folder.exists():
        print("[FAIL] Bundle file count: server/data/fhir/ folder not found -- run generate_fhir_bundles.py first")
        return False

    actual_count = len(list(fhir_output_folder.glob("*.json")))
    if actual_count != expected_count:
        print(f"[FAIL] Bundle file count: expected {expected_count} (one per encounter), found {actual_count}")
        return False

    print(f"[PASS] Bundle file count: {actual_count} bundle(s), matching {expected_count} encounter(s)")
    return True


def check_bundle_composition_first(fhir_output_folder):
    """
    WHY: a FHIR "document" Bundle's first entry MUST be the Composition
    (this is a hard rule in the FHIR spec, not just a convention) -- a
    validator or HIU consuming these bundles would reject anything else.
    """
    bad_files = []
    for path in fhir_output_folder.glob("*.json"):
        with open(path, encoding="utf-8") as f:
            bundle = json.load(f)
        first_resource_type = bundle.get("entry", [{}])[0].get("resource", {}).get("resourceType")
        if first_resource_type != "Composition":
            bad_files.append((path.name, first_resource_type))

    if bad_files:
        print(f"[FAIL] Composition is entry[0]: {len(bad_files)} bundle(s) violate this, e.g. {bad_files[0]}")
        return False

    print("[PASS] Composition is entry[0]: true for every bundle checked")
    return True


def check_bundle_internal_references_resolve(fhir_output_folder):
    """
    WHY: every "reference": "Patient/PAT9001" style value anywhere inside
    a bundle (in Encounter.subject, Condition.subject, Composition.section
    entries, etc.) should point to an entry that actually exists in that
    same bundle. A dangling reference means a resource was referenced but
    never included -- the bundle would be incomplete on the receiving end.

    EXAMPLE: if Composition references "Observation/OBS0042" in one of its
    sections, but no entry with resourceType "Observation" and id "OBS0042"
    exists anywhere in that bundle's entry list, this fails and names the
    bundle + the dangling reference.
    """
    bad = []
    checked_bundles = 0

    for path in fhir_output_folder.glob("*.json"):
        with open(path, encoding="utf-8") as f:
            bundle = json.load(f)

        available = {
            f"{entry['resource']['resourceType']}/{entry['resource']['id']}"
            for entry in bundle.get("entry", [])
        }

        found_references = []
        _extract_references(bundle, found_references)

        for reference in found_references:
            if reference not in available:
                bad.append(f"{path.name}: dangling reference {reference}")

        checked_bundles += 1

    if bad:
        print(f"[FAIL] Internal references resolve: {len(bad)} dangling reference(s), e.g. {bad[0]}")
        return False

    print(f"[PASS] Internal references resolve: checked {checked_bundles} bundle(s), no dangling references")
    return True


def main():

    print("\nValidating FHIR resource builders...\n")

    organizations = load_csv(MASTER_OUTPUT_FOLDER, "organizations.csv")
    practitioners = load_csv(MASTER_OUTPUT_FOLDER, "practitioners.csv")
    patients = load_csv(MASTER_OUTPUT_FOLDER, "patients.csv")
    encounters = load_csv(TRANSACTION_OUTPUT_FOLDER, "encounters.csv")
    conditions = load_csv(TRANSACTION_OUTPUT_FOLDER, "conditions.csv")
    observations = load_csv(TRANSACTION_OUTPUT_FOLDER, "observations.csv")
    medication_requests = load_csv(TRANSACTION_OUTPUT_FOLDER, "medication_requests.csv")
    procedures = load_csv(TRANSACTION_OUTPUT_FOLDER, "procedures.csv")
    diagnostic_reports = load_csv(TRANSACTION_OUTPUT_FOLDER, "diagnostic_reports.csv")
    immunizations = load_csv(TRANSACTION_OUTPUT_FOLDER, "immunizations.csv")

    sample_folder = Path(__file__).resolve().parents[1] / "server" / "data" / "fhir_samples"

    results = [
        run_builder_over_rows("Organization builder", organizations, build_organization, sample_folder / "organization_sample.json"),
        run_builder_over_rows("Practitioner builder", practitioners, build_practitioner, sample_folder / "practitioner_sample.json"),
        run_builder_over_rows("Patient builder", patients, build_patient, sample_folder / "patient_sample.json"),
        run_builder_over_rows("Encounter builder", encounters, build_encounter, sample_folder / "encounter_sample.json"),
        run_builder_over_rows("Condition builder", conditions, build_condition, sample_folder / "condition_sample.json"),
        run_builder_over_rows("Observation builder", observations, build_observation, sample_folder / "observation_sample.json"),
        run_builder_over_rows("MedicationRequest builder", medication_requests, build_medication_request, sample_folder / "medication_request_sample.json"),
        run_builder_over_rows("Procedure builder", procedures, build_procedure, sample_folder / "procedure_sample.json"),
        run_builder_over_rows("DiagnosticReport builder", diagnostic_reports, build_diagnostic_report, sample_folder / "diagnostic_report_sample.json"),
        run_builder_over_rows("Immunization builder", immunizations, build_immunization, sample_folder / "immunization_sample.json"),
    ]

    fhir_output_folder = Path(__file__).resolve().parents[1] / "server" / "data" / "fhir"
    results.append(check_bundle_file_count(fhir_output_folder, len(encounters)))
    results.append(check_bundle_composition_first(fhir_output_folder))
    results.append(check_bundle_internal_references_resolve(fhir_output_folder))

    passed = sum(results)
    print(f"\n{passed}/{len(results)} builder checks passed.\n")

    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
