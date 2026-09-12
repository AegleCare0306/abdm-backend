"""
generate_fhir_bundles.py

Reads the dummy EMR fixture data from Postgres (master + transaction
tables) and assembles one FHIR R4 document Bundle per encounter, writing
each to server/data/fhir/<encounter_reference>.json

This script is dummy-data-specific glue: it knows about the dummy EMR's
own row shapes, which the tools/ folder won't need once real EMR data
exists. The actual resource-construction logic it calls (server/fhir_builders/)
is the permanent, reusable part -- this script is just today's plumbing
from those rows to that logic.

HOW TO RUN
----------
    cd tools
    python generate_dummy_emr.py         # make sure the DB fixture data exists and is current
    python generate_fhir_bundles.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from server.config import DATABASE_URL
from server.db import init_engine

init_engine(DATABASE_URL)

from server.callbacks.repository import dummy_emr_repository as repository
from dummy_emr.case_library import CLINICAL_CASES

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
from server.fhir_builders.composition import build_composition
from server.fhir_builders.bundle import build_bundle


FHIR_OUTPUT_FOLDER = Path(__file__).resolve().parents[1] / "server" / "data" / "fhir"


def group_by(rows, key):
    grouped = {}
    for row in rows:
        grouped.setdefault(row[key], []).append(row)
    return grouped


def _to_fhir_instant(value):
    return value.replace(" ", "T") + "+05:30"


def main():

    print("\nAssembling FHIR bundles from the dummy EMR fixture data (Postgres)...\n")

    organizations = repository.get_all_organizations()
    practitioners = repository.get_all_practitioners()
    patients = repository.get_all_patients()
    encounters = repository.get_all_encounters()
    conditions = repository.get_all_conditions()
    observations = repository.get_all_observations()
    medication_requests = repository.get_all_medication_requests()
    procedures = repository.get_all_procedures()
    diagnostic_reports = repository.get_all_diagnostic_reports()
    immunizations = repository.get_all_immunizations()

    case_lookup = {case["case_id"]: case for case in CLINICAL_CASES}

    # Master resources are shared across many encounters -- build each once
    # and cache, rather than rebuilding an identical Patient/Practitioner/
    # Organization resource for every single encounter that references it.
    organization_cache = {org["hip_id"]: build_organization(org) for org in organizations}
    practitioner_cache = {p["practitioner_reference"]: build_practitioner(p) for p in practitioners}
    patient_cache = {p["patient_reference"]: build_patient(p) for p in patients}

    conditions_by_encounter = group_by(conditions, "encounter_reference")
    observations_by_encounter = group_by(observations, "encounter_reference")
    medication_requests_by_encounter = group_by(medication_requests, "encounter_reference")
    procedures_by_encounter = group_by(procedures, "encounter_reference")
    diagnostic_reports_by_encounter = group_by(diagnostic_reports, "encounter_reference")
    immunizations_by_encounter = group_by(immunizations, "encounter_reference")

    FHIR_OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    # Upsert by filename (== encounter_reference): only bundles for
    # encounters currently in encounters.csv are (re)written below: no
    # upfront wholesale delete, so a bundle for an encounter that somehow
    # isn't in this pass is never destroyed.

    written = 0

    for encounter_row in encounters:

        encounter_ref = encounter_row["encounter_reference"]
        patient_ref = encounter_row["patient_reference"]
        practitioner_ref = encounter_row["practitioner_reference"]
        hip_id = encounter_row["hip_id"]
        case = case_lookup[encounter_row["clinical_case"]]

        encounter_resource = build_encounter(encounter_row)

        condition_resources = [build_condition(row) for row in conditions_by_encounter.get(encounter_ref, [])]
        observation_resources = [build_observation(row) for row in observations_by_encounter.get(encounter_ref, [])]
        medication_request_resources = [build_medication_request(row) for row in medication_requests_by_encounter.get(encounter_ref, [])]
        procedure_resources = [build_procedure(row) for row in procedures_by_encounter.get(encounter_ref, [])]
        diagnostic_report_resources = [build_diagnostic_report(row) for row in diagnostic_reports_by_encounter.get(encounter_ref, [])]
        immunization_resources = [build_immunization(row) for row in immunizations_by_encounter.get(encounter_ref, [])]

        resource_ids_by_category = {
            "condition": [r["id"] for r in condition_resources],
            "medication_request": [r["id"] for r in medication_request_resources],
            "observation": [r["id"] for r in observation_resources],
            "diagnostic_report": [r["id"] for r in diagnostic_report_resources],
            "procedure": [r["id"] for r in procedure_resources],
            "immunization": [r["id"] for r in immunization_resources],
        }

        composition_id = f"COMP-{encounter_ref}"
        composition_resource = build_composition(
            composition_id=composition_id,
            patient_id=patient_ref,
            encounter_id=encounter_ref,
            practitioner_id=practitioner_ref,
            organization_id=hip_id,
            composition_date=encounter_row["encounter_datetime"],
            title=f"{encounter_row['visit_reason']} - {encounter_row['chief_complaint']}",
            document_types=case["document_types"],
            chief_complaint=encounter_row["chief_complaint"],
            resource_ids_by_category=resource_ids_by_category,
        )

        all_resources = (
            [patient_cache[patient_ref], practitioner_cache[practitioner_ref], organization_cache[hip_id], encounter_resource]
            + condition_resources
            + observation_resources
            + medication_request_resources
            + procedure_resources
            + diagnostic_report_resources
            + immunization_resources
        )

        bundle = build_bundle(
            bundle_id=f"BUNDLE-{encounter_ref}",
            composition=composition_resource,
            resources=all_resources,
            timestamp=_to_fhir_instant(encounter_row["encounter_datetime"]),
        )

        output_path = FHIR_OUTPUT_FOLDER / f"{encounter_ref}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2)

        written += 1

    print(f"Wrote {written} FHIR bundle(s) to {FHIR_OUTPUT_FOLDER}\n")


if __name__ == "__main__":
    main()
