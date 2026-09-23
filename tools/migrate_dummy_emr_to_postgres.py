"""
One-time backfill: the dummy EMR fixture CSVs -> Postgres.

WHY THIS EXISTS. The dummy-EMR-to-Postgres chunk built the schema
(server/db_models.py's own "Dummy EMR" section), the repository
(server/callbacks/repository/dummy_emr_repository.py) and every consumer
refactor, but the actual DATA migration was left pending and never ran.
Result, found live 2026-09-23: all fourteen tables empty while the source
CSVs sat intact on disk -- so patient_repository.search_patient() returned
nothing, the Discover/Link-Confirm callbacks could not find a patient, and
the M2/M3 CLIs had no care contexts to offer. This closes that gap.

SAFE TO RE-RUN. Every write goes through the repository's own insert_*
functions, which are upserts keyed on each table's natural key, so a second
run updates rows rather than duplicating them. It also means a partial run
(interrupted halfway) can simply be run again.

THE CSVs ARE NOT DELETED OR MODIFIED. They stay exactly where they are as
the audit trail of what was migrated.

FK-SAFE ORDER, which is why the table list below is hand-ordered rather
than globbed: organizations/patients/practitioners have no parents ->
practitioner_organizations needs the first and third -> encounters need
organizations + patients + practitioners -> every clinical child table
needs encounters -> patient_records needs organizations + patients +
encounters.

HOW TO RUN
----------
    cd tools
    python migrate_dummy_emr_to_postgres.py
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from server.config import DATABASE_URL
from server.db import init_engine

init_engine(DATABASE_URL)

from server.callbacks.repository import dummy_emr_repository as repository

_MASTER = _REPO_ROOT / "server" / "data" / "master"
_TRANSACTION = _REPO_ROOT / "server" / "data" / "transaction"
_PATIENT_RECORDS = _REPO_ROOT / "server" / "data" / "patient_records.csv"


def _read(path: Path) -> list[dict]:
    if not path.exists():
        print(f"  SKIP (missing): {path.name}")
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load(label: str, path: Path, insert, transform=None) -> int:
    rows = _read(path)
    for row in rows:
        insert(transform(row) if transform else row)
    print(f"  {label:<28} {len(rows):>4} row(s)")
    return len(rows)


def _patient_row(row: dict) -> dict:
    """
    patients.csv stores date_of_birth as DD-MM-YYYY text; the column is a
    real DATE. The repository's own coercion assumes ISO for Date columns,
    so the day-first format has to be parsed HERE -- exactly what
    tools/generate_dummy_emr.py does at its own insert_patient() call site.
    """
    out = dict(row)
    dob = (out.get("date_of_birth") or "").strip()
    out["date_of_birth"] = datetime.strptime(dob, "%d-%m-%Y").date() if dob else None
    return out


def main() -> None:
    print("\nBackfilling the dummy EMR fixture data into Postgres...\n")

    total = 0
    print("Master (no foreign keys):")
    total += _load("organizations", _MASTER / "organizations.csv", repository.insert_organization)
    total += _load("patients", _MASTER / "patients.csv", repository.insert_patient, _patient_row)
    total += _load("practitioners", _MASTER / "practitioners.csv", repository.insert_practitioner)

    print("\nJoin table (needs practitioners + organizations):")
    total += _load("practitioner_organizations", _MASTER / "practitioner_organizations.csv",
                   repository.insert_practitioner_organization)

    print("\nEncounters (needs organizations + patients + practitioners):")
    total += _load("encounters", _TRANSACTION / "encounters.csv", repository.insert_encounter)

    print("\nClinical children (each needs encounters + patients):")
    for label, filename, insert in [
        ("conditions", "conditions.csv", repository.insert_condition),
        ("observations", "observations.csv", repository.insert_observation),
        ("medication_requests", "medication_requests.csv", repository.insert_medication_request),
        ("procedures", "procedures.csv", repository.insert_procedure),
        ("diagnostic_reports", "diagnostic_reports.csv", repository.insert_diagnostic_report),
        ("immunizations", "immunizations.csv", repository.insert_immunization),
        ("documents", "documents.csv", repository.insert_document),
        ("billing", "billing.csv", repository.insert_billing),
    ]:
        total += _load(label, _TRANSACTION / filename, insert)

    print("\nCare-context discovery table (needs organizations + patients + encounters):")
    total += _load("patient_records", _PATIENT_RECORDS, repository.insert_patient_record)

    print(f"\nDone. {total} row(s) written.\n")


if __name__ == "__main__":
    main()
