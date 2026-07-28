"""
Health Information Data Service.

Given a list of consented care context references, fetches the underlying
records and assembles one FHIR document Bundle per care context.

CURRENT DATA SOURCE: the dummy EMR CSVs under tools/dummy_emr, since
that's the only "database" that exists right now. This is the one part
of this file that will need to change once real EMR data access exists --
swap the CSV loads below for real queries (by care context / encounter
reference) and everything else stays the same, since server/fhir_builders/
was written to take plain dicts, not CSV rows specifically -- it doesn't
know or care where the dict came from.

This duplicates some of tools/generate_fhir_bundles.py's logic by design:
that script builds bundles for EVERY encounter (for testing/dev), while
this service builds bundles only for the SPECIFIC care contexts a real
consent actually covers. Worth consolidating into one shared data-access
layer once real EMR queries replace the CSV reads here -- premature to
force that abstraction now, before knowing what the real data access
pattern looks like.
"""

import csv
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parents[3] / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from dummy_emr.config import MASTER_OUTPUT_FOLDER, TRANSACTION_OUTPUT_FOLDER
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


def _load_csv(folder, filename):
    with open(Path(folder) / filename, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _to_fhir_instant(value):
    return value.replace(" ", "T") + "+05:30"


def _rows_for_encounter(rows, encounter_reference):
    return [row for row in rows if row["encounter_reference"] == encounter_reference]


def build_bundles_for_care_contexts(care_context_references):
    """
    care_context_references: list of strings, e.g. ["ENC0005", "ENC0012"].
    These map 1:1 to encounter_reference in the mock data today -- once
    real EMR data exists, a "care context" may need its own explicit
    mapping to whatever the real system's encounter/episode ID is.

    Returns a list of finished FHIR document Bundle dicts -- one per
    care context that was actually found. A requested care context with
    no matching record is silently skipped rather than raising, since a
    consent could in principle reference something no longer present;
    the caller can compare len(result) against len(care_context_references)
    to detect that.
    """

    organizations = _load_csv(MASTER_OUTPUT_FOLDER, "organizations.csv")
    practitioners = _load_csv(MASTER_OUTPUT_FOLDER, "practitioners.csv")
    patients = _load_csv(MASTER_OUTPUT_FOLDER, "patients.csv")
    encounters = _load_csv(TRANSACTION_OUTPUT_FOLDER, "encounters.csv")
    conditions = _load_csv(TRANSACTION_OUTPUT_FOLDER, "conditions.csv")
    observations = _load_csv(TRANSACTION_OUTPUT_FOLDER, "observations.csv")
    medication_requests = _load_csv(TRANSACTION_OUTPUT_FOLDER, "medication_requests.csv")
    procedures = _load_csv(TRANSACTION_OUTPUT_FOLDER, "procedures.csv")
    diagnostic_reports = _load_csv(TRANSACTION_OUTPUT_FOLDER, "diagnostic_reports.csv")
    immunizations = _load_csv(TRANSACTION_OUTPUT_FOLDER, "immunizations.csv")

    case_lookup = {case["case_id"]: case for case in CLINICAL_CASES}
    organization_by_hip = {org["hip_id"]: org for org in organizations}
    practitioner_by_ref = {p["practitioner_reference"]: p for p in practitioners}
    patient_by_ref = {p["patient_reference"]: p for p in patients}
    encounter_by_ref = {e["encounter_reference"]: e for e in encounters}

    bundles = []

    for care_context_reference in care_context_references:

        encounter_row = encounter_by_ref.get(care_context_reference)
        if encounter_row is None:
            continue

        patient_row = patient_by_ref[encounter_row["patient_reference"]]
        practitioner_row = practitioner_by_ref[encounter_row["practitioner_reference"]]
        organization_row = organization_by_hip[encounter_row["hip_id"]]
        case = case_lookup[encounter_row["clinical_case"]]

        patient_resource = build_patient(patient_row)
        practitioner_resource = build_practitioner(practitioner_row)
        organization_resource = build_organization(organization_row)
        encounter_resource = build_encounter(encounter_row)

        condition_resources = [build_condition(r) for r in _rows_for_encounter(conditions, care_context_reference)]
        observation_resources = [build_observation(r) for r in _rows_for_encounter(observations, care_context_reference)]
        medication_request_resources = [build_medication_request(r) for r in _rows_for_encounter(medication_requests, care_context_reference)]
        procedure_resources = [build_procedure(r) for r in _rows_for_encounter(procedures, care_context_reference)]
        diagnostic_report_resources = [build_diagnostic_report(r) for r in _rows_for_encounter(diagnostic_reports, care_context_reference)]
        immunization_resources = [build_immunization(r) for r in _rows_for_encounter(immunizations, care_context_reference)]

        resource_ids_by_category = {
            "condition": [r["id"] for r in condition_resources],
            "medication_request": [r["id"] for r in medication_request_resources],
            "observation": [r["id"] for r in observation_resources],
            "diagnostic_report": [r["id"] for r in diagnostic_report_resources],
            "procedure": [r["id"] for r in procedure_resources],
            "immunization": [r["id"] for r in immunization_resources],
        }

        composition_resource = build_composition(
            composition_id=f"COMP-{care_context_reference}",
            patient_id=patient_row["patient_reference"],
            encounter_id=care_context_reference,
            practitioner_id=practitioner_row["practitioner_reference"],
            organization_id=organization_row["hip_id"],
            composition_date=encounter_row["encounter_datetime"],
            title=f"{encounter_row['visit_reason']} - {encounter_row['chief_complaint']}",
            document_types=case["document_types"],
            chief_complaint=encounter_row["chief_complaint"],
            resource_ids_by_category=resource_ids_by_category,
        )

        all_resources = (
            [patient_resource, practitioner_resource, organization_resource, encounter_resource]
            + condition_resources
            + observation_resources
            + medication_request_resources
            + procedure_resources
            + diagnostic_report_resources
            + immunization_resources
        )

        bundle = build_bundle(
            bundle_id=f"BUNDLE-{care_context_reference}",
            composition=composition_resource,
            resources=all_resources,
            timestamp=_to_fhir_instant(encounter_row["encounter_datetime"]),
        )

        bundles.append(bundle)

    return bundles
