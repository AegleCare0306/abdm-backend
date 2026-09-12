"""
validate_output.py

Standalone validation script for the dummy EMR fixture data.

WHAT THIS DOES
--------------
After running `generate_dummy_emr.py`, run this script to check that the
generated data (in Postgres -- see server/callbacks/repository/
dummy_emr_repository.py) is internally consistent and clinically
sensible. It does NOT regenerate any data — it only reads and checks
what's already in the database.

HOW TO RUN
----------
    cd tools
    python3 generate_dummy_emr.py     # generate/refresh the data first
    python3 validate_output.py        # then validate it

HOW TO READ THE OUTPUT
-----------------------
Each check prints one line:

    [PASS] <check name> - <what it checks>
    [FAIL] <check name> - <what it checks>
               -> <details of what went wrong>

A summary line at the end shows how many checks passed out of the total.
Every check is a small, independent function below (see CHECKS list at the
bottom) — add a new one by writing a function with the same signature and
appending it to CHECKS. Each function's docstring explains WHY the check
exists and gives a worked example, so this file also serves as a reference
for anyone new to the project on what "correct" output looks like.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.config import DATABASE_URL
from server.db import init_engine

init_engine(DATABASE_URL)

from server.callbacks.repository import dummy_emr_repository as repository
from dummy_emr.case_library import CLINICAL_CASES
from dummy_emr.master_data.diagnoses import DIAGNOSES
from dummy_emr.master_data.medications import MEDICATIONS
from dummy_emr.master_data.lab_tests import LAB_TESTS
from dummy_emr.master_data.procedures import PROCEDURES
from dummy_emr.master_data.vaccines import VACCINES


class Result:
    """Carries the outcome of one check: whether it passed, and a short
    human-readable detail line to show on failure (or on pass, if useful)."""

    def __init__(self, passed, detail=""):
        self.passed = passed
        self.detail = detail


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_all_tables_populated(data):
    """
    WHY: If generate_dummy_emr.py silently failed partway through (e.g. an
    exception after some writes), some tables might be empty entirely.
    This check catches that before any of the other checks even run.

    EXAMPLE: if 'billing' has zero rows, this fails with "empty: billing"
    instead of every downstream check crashing on missing data.
    """

    expected_nonempty = [
        "organizations", "practitioners", "practitioner_organizations", "patients",
        "encounters", "conditions", "observations", "medication_requests",
        "diagnostic_reports", "procedures", "documents", "immunizations", "billing",
    ]

    empty = [name for name in expected_nonempty if not data[name]]

    if empty:
        return Result(False, f"empty: {', '.join(empty)}")
    return Result(True, f"all {len(expected_nonempty)} tables populated")


def check_encounter_references_resolve(data):
    """
    WHY: Every clinical CSV (conditions, observations, medication_requests,
    diagnostic_reports, procedures, documents, immunizations, billing)
    carries an encounter_reference. If any of these point to an encounter
    that doesn't exist in encounters.csv, it means a generator used a stale
    or mismatched reference — a real bug, not a data quirk.

    EXAMPLE: conditions.csv row with encounter_reference "ENC0999" but
    encounters.csv only goes up to "ENC0080" -> this check fails and names
    the file + the bad reference.
    """

    encounter_refs = {row["encounter_reference"] for row in data["encounters"]}

    child_files = [
        "conditions", "observations", "medication_requests",
        "diagnostic_reports", "procedures", "documents",
        "immunizations", "billing",
    ]

    bad = []
    for name in child_files:
        for row in data[name]:
            if row["encounter_reference"] not in encounter_refs:
                bad.append(f"{name}.csv -> {row['encounter_reference']}")

    if bad:
        return Result(False, f"{len(bad)} dangling encounter_reference(s), e.g. {bad[0]}")
    return Result(True, f"checked {len(child_files)} files against {len(encounter_refs)} encounters")


def check_patient_references_resolve(data):
    """
    WHY: Same idea as the encounter check, but for patient_reference. This
    catches a subtler bug: a row could reference a *real* encounter but the
    *wrong* patient on it (e.g. a copy-paste mismatch inside a generator),
    which the encounter check alone wouldn't catch.

    EXAMPLE: a billing.csv row says patient_reference "PAT0005" but the
    encounter_reference on that same row actually belongs to "PAT0002" in
    encounters.csv -> flagged as a mismatch, not just a missing reference.
    """

    encounter_to_patient = {
        row["encounter_reference"]: row["patient_reference"]
        for row in data["encounters"]
    }

    child_files = [
        "conditions", "observations", "medication_requests",
        "diagnostic_reports", "procedures", "documents",
        "immunizations", "billing",
    ]

    bad = []
    for name in child_files:
        for row in data[name]:
            expected_patient = encounter_to_patient.get(row["encounter_reference"])
            if expected_patient is not None and row["patient_reference"] != expected_patient:
                bad.append(
                    f"{name}.csv row on {row['encounter_reference']}: "
                    f"has patient {row['patient_reference']}, expected {expected_patient}"
                )

    if bad:
        return Result(False, f"{len(bad)} patient/encounter mismatch(es), e.g. {bad[0]}")
    return Result(True, "every row's patient_reference matches its encounter's patient")


def check_diagnosis_references_resolve(data):
    """
    WHY: conditions.csv stores diagnosis_reference (e.g. "DXGM001") rather
    than repeating the condition name/ICD-10/SNOMED inline. If that
    reference doesn't exist in the diagnoses master, every downstream FHIR
    Condition resource built from this row would have no coding to attach.

    EXAMPLE: conditions.csv row with diagnosis_reference "DXGM099" that
    doesn't exist in any of the 15 department diagnosis files -> fails and
    names the bad reference.
    """

    valid_refs = {d["diagnosis_reference"] for d in DIAGNOSES}

    bad = [
        row["diagnosis_reference"]
        for row in data["conditions"]
        if row["diagnosis_reference"] not in valid_refs
    ]

    if bad:
        return Result(False, f"{len(bad)} unresolvable diagnosis_reference(s), e.g. {bad[0]}")
    return Result(True, f"all {len(data['conditions'])} conditions resolve against {len(valid_refs)} diagnoses")


def check_clinical_case_references_resolve(data):
    """
    WHY: encounters.csv stores which clinical_case (e.g. "CASE004") was used
    to generate that visit. Every downstream generator (conditions,
    observations, medication_requests, etc.) looks the case back up by this
    ID. If it doesn't exist in case_library.py, that lookup would crash --
    so this check would catch it before you even get to run those
    generators.

    EXAMPLE: an encounter with clinical_case "CASE999" when case_library.py
    only defines CASE001-CASE080 -> fails.
    """

    valid_case_ids = {case["case_id"] for case in CLINICAL_CASES}

    bad = [
        row["clinical_case"]
        for row in data["encounters"]
        if row["clinical_case"] not in valid_case_ids
    ]

    if bad:
        return Result(False, f"{len(bad)} unresolvable clinical_case reference(s), e.g. {bad[0]}")
    return Result(True, f"all {len(data['encounters'])} encounters resolve against {len(valid_case_ids)} cases")


def check_catalog_item_references_resolve(data):
    """
    WHY: medication_requests/diagnostic_reports/procedures/immunizations
    each store a reference into their respective master catalog
    (medication_reference, lab_reference, procedure_master_reference,
    vaccine_reference). If any of these are wrong, the FHIR builders would
    later produce a resource pointing at a drug/test/procedure/vaccine that
    doesn't exist in your masters.

    EXAMPLE: a medication_requests.csv row with medication_reference
    "MED000099" when only MED000001-MED000026 exist -> fails.
    """

    valid_meds = {m["medication_reference"] for m in MEDICATIONS}
    valid_labs = {l["lab_reference"] for l in LAB_TESTS}
    valid_procs = {p["procedure_reference"] for p in PROCEDURES}
    valid_vaccines = {v["vaccine_reference"] for v in VACCINES}

    bad = []

    for row in data["medication_requests"]:
        if row["medication_reference"] not in valid_meds:
            bad.append(f"medication_requests.csv -> {row['medication_reference']}")

    for row in data["diagnostic_reports"]:
        if row["lab_reference"] not in valid_labs:
            bad.append(f"diagnostic_reports.csv -> {row['lab_reference']}")

    for row in data["procedures"]:
        if row["procedure_master_reference"] not in valid_procs:
            bad.append(f"procedures.csv -> {row['procedure_master_reference']}")

    for row in data["immunizations"]:
        if row["vaccine_reference"] not in valid_vaccines:
            bad.append(f"immunizations.csv -> {row['vaccine_reference']}")

    if bad:
        return Result(False, f"{len(bad)} unresolvable catalog reference(s), e.g. {bad[0]}")
    return Result(True, "every medication/lab/procedure/vaccine reference resolves")


def check_no_duplicate_primary_keys(data):
    """
    WHY: each CSV's own reference column (e.g. encounter_reference in
    encounters.csv, invoice_reference in billing.csv) should be unique --
    a duplicate usually means the output folder wasn't cleared before a
    re-run, so old and new rows got mixed together.

    EXAMPLE: running generate_dummy_emr.py twice without clearing output
    first would (if clear_output_folder() were broken) leave two rows both
    named "ENC0001" -> this check fails and names the file + duplicate ID.
    """

    key_column = {
        "encounters": "encounter_reference",
        "conditions": "condition_reference",
        "observations": "observation_reference",
        "medication_requests": "medication_request_reference",
        "diagnostic_reports": "diagnostic_report_reference",
        "procedures": "procedure_reference",
        "documents": "document_reference",
        "immunizations": "immunization_reference",
        "billing": "invoice_reference",
    }

    bad = []
    for name, column in key_column.items():
        seen = set()
        for row in data[name]:
            value = row[column]
            if value in seen:
                bad.append(f"{name}.csv has duplicate {column}: {value}")
            seen.add(value)

    if bad:
        return Result(False, f"{len(bad)} duplicate key(s), e.g. {bad[0]}")
    return Result(True, f"checked {len(key_column)} files for duplicate primary keys")


def check_billing_math(data):
    """
    WHY: billing.csv's total_amount is computed as consultation_fee +
    pharmacy_charge + investigation_charge + procedure_charge. If a future
    change to billing.py breaks that formula, invoices would silently be
    wrong -- this check re-derives the total independently and compares.

    EXAMPLE: a row with consultation_fee=600, pharmacy_charge=30.0,
    investigation_charge=1250.0, procedure_charge=100 must have
    total_amount exactly 1980.0 -> if it instead says 1980.5, this fails.
    """

    bad = []
    for row in data["billing"]:
        expected_total = round(
            float(row["consultation_fee"])
            + float(row["pharmacy_charge"])
            + float(row["investigation_charge"])
            + float(row["procedure_charge"]),
            2,
        )
        actual_total = round(float(row["total_amount"]), 2)
        if abs(expected_total - actual_total) > 0.01:
            bad.append(
                f"{row['invoice_reference']}: expected {expected_total}, got {actual_total}"
            )

    if bad:
        return Result(False, f"{len(bad)} invoice(s) with wrong totals, e.g. {bad[0]}")
    return Result(True, f"all {len(data['billing'])} invoice totals add up correctly")


def check_one_invoice_per_encounter(data):
    """
    WHY: unlike observations/medications/labs (which are optional per
    case), every encounter should always be billed at least a consultation
    fee -- so billing.csv should have exactly one row per encounter, no
    more, no less.

    EXAMPLE: 80 encounters generated -> billing.csv should have exactly
    80 rows. If it has 79 (a visit slipped through unbilled) or 81 (a
    visit billed twice), this fails.
    """

    encounter_count = len(data["encounters"])
    billing_count = len(data["billing"])

    if encounter_count != billing_count:
        return Result(
            False,
            f"{encounter_count} encounters but {billing_count} billing rows",
        )
    return Result(True, f"{billing_count} encounters, {billing_count} invoices")


def check_hypertension_bp_elevated(data):
    """
    WHY: the observation generator is supposed to raise blood pressure
    values for cases whose diagnosis name matches hypertension-related
    keywords, rather than always generating "normal" vitals. This is a
    clinical-plausibility check, not just a structural one.

    EXAMPLE: for the "Essential Hypertension" case, a Blood Pressure
    observation reading like "170/100" is expected; something like
    "115/75" on that same case would fail this check.
    """

    condition_by_encounter = {
        row["encounter_reference"]: row["condition_name"]
        for row in data["conditions"]
    }

    checked = 0
    bad = []

    for row in data["observations"]:
        if row["name"] != "Blood Pressure":
            continue

        condition_name = condition_by_encounter.get(row["encounter_reference"], "")
        if "hypertens" not in condition_name.lower():
            continue

        checked += 1
        systolic = int(row["value"].split("/")[0])
        if systolic < 135:
            bad.append(f"{row['encounter_reference']} ({condition_name}): BP {row['value']}")

    if checked == 0:
        return Result(False, "no hypertension-related BP observations found to check")
    if bad:
        return Result(False, f"{len(bad)}/{checked} hypertensive case(s) with non-elevated BP, e.g. {bad[0]}")
    return Result(True, f"all {checked} hypertension-related BP readings were elevated")


def check_diabetic_glucose_elevated(data):
    """
    WHY: same idea as the blood pressure check, but for blood glucose on
    diabetes-related cases -- confirms the observation generator's
    keyword-matching logic is actually being triggered, not just present
    in the code but silently never firing.

    EXAMPLE: for "Type 2 Diabetes Mellitus", a Blood Glucose observation
    of 200 mg/dL is expected; 95 mg/dL on that same case would fail.
    """

    condition_by_encounter = {
        row["encounter_reference"]: row["condition_name"]
        for row in data["conditions"]
    }

    checked = 0
    bad = []

    for row in data["observations"]:
        if row["name"] != "Blood Glucose":
            continue

        condition_name = condition_by_encounter.get(row["encounter_reference"], "")
        if "diabetes" not in condition_name.lower():
            continue

        checked += 1
        value = int(row["value"])
        if value < 140:
            bad.append(f"{row['encounter_reference']} ({condition_name}): glucose {value}")

    if checked == 0:
        return Result(False, "no diabetes-related glucose observations found to check")
    if bad:
        return Result(False, f"{len(bad)}/{checked} diabetic case(s) with non-elevated glucose, e.g. {bad[0]}")
    return Result(True, f"all {checked} diabetes-related glucose readings were elevated")


def check_antibiotic_course_pattern(data):
    """
    WHY: medication_requests.py has a special rule -- any tablet/capsule
    whose ATC code starts with "J0" (antibacterials) should get a 5-day,
    thrice-daily course rather than the default frequency. This check
    confirms that rule is actually being applied in the output.

    EXAMPLE: Amoxicillin (ATC J01CA04) prescribed anywhere should show
    frequency "Thrice daily" and duration_days "5" -- if it instead shows
    "Twice daily" / "90", the ATC-prefix check in the generator broke.
    """

    antibiotic_generics = {
        m["generic_name"] for m in MEDICATIONS if (m["atc_code"] or "").startswith("J0")
    }

    checked = 0
    bad = []

    for row in data["medication_requests"]:
        if row["generic_name"] not in antibiotic_generics:
            continue
        checked += 1
        if row["frequency"] != "Thrice daily" or row["duration_days"] != "5":
            bad.append(
                f"{row['medication_request_reference']} ({row['generic_name']}): "
                f"{row['frequency']}, {row['duration_days']} days"
            )

    if checked == 0:
        return Result(False, "no antibiotic medication_requests found to check")
    if bad:
        return Result(False, f"{len(bad)}/{checked} antibiotic course(s) not matching expected pattern, e.g. {bad[0]}")
    return Result(True, f"all {checked} antibiotic prescriptions follow the 5-day/thrice-daily pattern")


def check_immunizations_only_on_expected_case(data):
    """
    WHY: only one case in the library (the pediatric routine immunization
    visit) carries vaccine_references. If immunizations.csv has rows tied
    to any other clinical_case, something is generating vaccines it
    shouldn't be.

    EXAMPLE: an immunization row on an encounter whose clinical_case maps
    to "Essential Hypertension" instead of "Routine Immunization Visit"
    would fail this check.
    """

    cases_with_vaccines = {
        case["case_id"] for case in CLINICAL_CASES if case["vaccine_references"]
    }

    encounter_to_case = {
        row["encounter_reference"]: row["clinical_case"]
        for row in data["encounters"]
    }

    bad = []
    for row in data["immunizations"]:
        case_id = encounter_to_case.get(row["encounter_reference"])
        if case_id not in cases_with_vaccines:
            bad.append(f"{row['immunization_reference']} on case {case_id}")

    if bad:
        return Result(False, f"{len(bad)} unexpected immunization row(s), e.g. {bad[0]}")
    return Result(True, f"all {len(data['immunizations'])} immunization rows are on the expected case(s)")


def check_empty_reference_lists_produce_no_rows(data):
    """
    WHY: cases with an empty medication_references/observation_references/
    lab_references/procedure_references list (e.g. "Low Back Pain" has no
    medications) should produce zero rows in the corresponding CSV for
    that encounter -- not a blank/placeholder row.

    EXAMPLE: "Low Back Pain" (CASE ref with medication_references: [])
    used on encounter "ENC0012" -> medication_requests.csv should have
    NO rows with encounter_reference "ENC0012".
    """

    case_lookup = {case["case_id"]: case for case in CLINICAL_CASES}

    field_to_file = [
        ("medication_references", "medication_requests"),
        ("observation_references", "observations"),
        ("lab_references", "diagnostic_reports"),
        ("procedure_references", "procedures"),
    ]

    bad = []
    for case_field, csv_name in field_to_file:
        encounters_with_empty_list = {
            row["encounter_reference"]
            for row in data["encounters"]
            if not case_lookup[row["clinical_case"]][case_field]
        }
        rows_present = {row["encounter_reference"] for row in data[csv_name]}
        unexpected = encounters_with_empty_list & rows_present
        if unexpected:
            bad.append(f"{csv_name}.csv has rows for {len(unexpected)} encounter(s) with an empty {case_field}")

    if bad:
        return Result(False, "; ".join(bad))
    return Result(True, "encounters with an empty reference list produce zero rows in the matching CSV")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

# Checks that need the loaded data passed in
DATA_CHECKS = [
    ("All tables populated", check_all_tables_populated),
    ("Encounter references resolve", check_encounter_references_resolve),
    ("Patient references resolve", check_patient_references_resolve),
    ("Diagnosis references resolve", check_diagnosis_references_resolve),
    ("Clinical case references resolve", check_clinical_case_references_resolve),
    ("Catalog item references resolve", check_catalog_item_references_resolve),
    ("No duplicate primary keys", check_no_duplicate_primary_keys),
    ("Billing math adds up", check_billing_math),
    ("One invoice per encounter", check_one_invoice_per_encounter),
    ("Hypertension cases show elevated BP", check_hypertension_bp_elevated),
    ("Diabetic cases show elevated glucose", check_diabetic_glucose_elevated),
    ("Antibiotics follow 5-day/thrice-daily pattern", check_antibiotic_course_pattern),
    ("Immunizations only on the expected case", check_immunizations_only_on_expected_case),
    ("Empty reference lists produce no rows", check_empty_reference_lists_produce_no_rows),
]


def main():

    print("\nValidating dummy EMR output...\n")

    results = []

    data = {
        "organizations": repository.get_all_organizations(),
        "practitioners": repository.get_all_practitioners(),
        "practitioner_organizations": repository.get_practitioner_organizations(),
        "patients": repository.get_all_patients(),
        "encounters": repository.get_all_encounters(),
        "conditions": repository.get_all_conditions(),
        "observations": repository.get_all_observations(),
        "medication_requests": repository.get_all_medication_requests(),
        "diagnostic_reports": repository.get_all_diagnostic_reports(),
        "procedures": repository.get_all_procedures(),
        "documents": repository.get_all_documents(),
        "immunizations": repository.get_all_immunizations(),
        "billing": repository.get_all_billing(),
    }

    for name, check_fn in DATA_CHECKS:
        result = check_fn(data)
        results.append((name, result))

    _print_results(results)

    if not all(result.passed for _, result in results):
        sys.exit(1)


def _print_results(results):

    for name, result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {name}")
        if result.detail:
            print(f"         -> {result.detail}")

    passed_count = sum(1 for _, result in results if result.passed)
    total_count = len(results)

    print(f"\n{passed_count}/{total_count} checks passed.\n")


if __name__ == "__main__":
    main()
