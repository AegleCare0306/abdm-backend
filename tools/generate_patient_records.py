"""
generate_patient_records.py

Generates server/data/patient_records.csv -- the care-context mapping file
that server/callbacks/repository/patient_repository.py reads to serve the
Discover and Link-Confirm callbacks.

This replaces what was previously a hand-crafted CSV made during early
manual testing. It's now built from the actual mock EMR data (patients.csv,
encounters.csv, case_library.py) so care contexts reflect real generated
encounters instead of a few manually-typed rows.

Column schema is dictated by patient_repository.py (server/callbacks/
repository/patient_repository.py) -- it is NOT changed by this script;
this script only produces data in the shape that file already expects:
    abha_address, abha_number, mobile, mr_number, facility_id,
    patient_reference, name, care_context_reference, care_context_display,
    hi_type

One row is written per (encounter, hi_type) pair -- an encounter with both
a Prescription and a Diagnostic Report produces two rows sharing the same
care_context_reference (the encounter_reference) but different hi_type,
matching how ABDM's discovery response groups care contexts by HI Type.

This script always recomputes from the complete, current encounters.csv/
patients.csv (already fully merged by generate_dummy_emr.py before this
runs) -- but writes upsert-by-key (care_context_reference), replacing only
the rows for encounters currently on file and leaving any row whose
encounter no longer resolves (shouldn't normally happen) untouched, rather
than blindly overwriting the whole file.

HOW TO RUN
----------
    cd tools
    python generate_dummy_emr.py     # make sure mock data is current
    python generate_patient_records.py
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dummy_emr.config import MASTER_OUTPUT_FOLDER, TRANSACTION_OUTPUT_FOLDER
from dummy_emr.case_library import CLINICAL_CASES
from dummy_emr.hi_types import hi_types_for_case


OUTPUT_PATH = Path(__file__).resolve().parents[1] / "server" / "data" / "patient_records.csv"

FIELDNAMES = [
    "abha_address", "abha_number", "mobile", "mr_number", "facility_id",
    "patient_reference", "name", "care_context_reference",
    "care_context_display", "hi_type",
]


def load_csv(folder, filename):
    with open(Path(folder) / filename, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_existing_output():
    if not OUTPUT_PATH.exists():
        return []
    with open(OUTPUT_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():

    print("\nGenerating patient_records.csv from mock EMR data...\n")

    patients = load_csv(MASTER_OUTPUT_FOLDER, "patients.csv")
    encounters = load_csv(TRANSACTION_OUTPUT_FOLDER, "encounters.csv")
    case_lookup = {case["case_id"]: case for case in CLINICAL_CASES}
    patient_lookup = {p["patient_reference"]: p for p in patients}

    # Upsert by care_context_reference (== encounter_reference): existing
    # rows for an encounter no longer present in encounters.csv are kept
    # as-is (defensive; this shouldn't happen since encounters are never
    # deleted); every encounter currently on file gets its hi_type rows
    # (re)computed and replaces whatever it had before.
    existing_rows = load_existing_output()
    rows_by_encounter = {}
    order = []
    for row in existing_rows:
        key = row["care_context_reference"]
        if key not in rows_by_encounter:
            order.append(key)
        rows_by_encounter.setdefault(key, []).append(row)

    for encounter in encounters:

        patient = patient_lookup[encounter["patient_reference"]]
        case = case_lookup[encounter["clinical_case"]]

        care_context_display = f"{case['name']} - {encounter['encounter_datetime'][:10]}"

        key = encounter["encounter_reference"]
        if key not in rows_by_encounter:
            order.append(key)

        rows_by_encounter[key] = [
            {
                "abha_address": patient["abha_address"],
                "abha_number": patient["abha_number"],
                "mobile": patient["mobile"],
                "mr_number": encounter["mr_number"],
                "facility_id": encounter["hip_id"],
                "patient_reference": patient["patient_reference"],
                "name": patient["full_name"],
                "care_context_reference": encounter["encounter_reference"],
                "care_context_display": care_context_display,
                "hi_type": hi_type,
            }
            for hi_type in sorted(hi_types_for_case(case))
        ]

    rows = [row for key in order for row in rows_by_encounter[key]]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} care-context row(s) (from {len(encounters)} encounters) to {OUTPUT_PATH}\n")


if __name__ == "__main__":
    main()
