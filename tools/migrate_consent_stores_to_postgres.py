"""
One-time backfill (P16, 2026-09-07): copies every row currently in the
three file-backed stores this project depends on for things that already
work (e.g. Data Flow's self-view fetch reads real rows in
storage/hiu_consents.jsonl today) into the new Postgres tables, before the
repository modules are cut over to read from Postgres instead of these
files.

Run ONCE, before relying on the Postgres-backed repository modules for
anything: `python -m tools.migrate_consent_stores_to_postgres` from the
repo root (with `alembic upgrade head` already applied, so the target
tables exist).

Reads via the EXISTING server/callbacks/utils/json_file_store.py's own
get_all() -- already correct (replays the append-only log, latest line per
key wins, tombstones removed), reused rather than re-parsing the .jsonl
files by hand. Writes via the repository modules' own save_*() functions
(hiu_consent_repository.save_hiu_consent(), consent_repository.save_consent(),
patient_identity_repository.save_patient_identity()) -- reusing the exact
same upsert logic those modules already use for their normal write path,
rather than duplicating INSERT/ON CONFLICT SQL a third time here.

DOES NOT delete or truncate storage/hiu_consents.jsonl, storage/consents.jsonl,
or storage/patient_identities.jsonl -- standing rule, also just sensible
here: they become an inert audit trail after cutover, not the live source
of truth anymore, but nothing about this script (or the code it backfills
for) ever reads them again once the repository modules are Postgres-backed.
Safe to re-run -- every write here is an upsert (same "always overwrites,
no merge" contract the live repository modules use), so running this
script twice just re-applies the same rows.
"""

from server.callbacks.repository import consent_repository, hiu_consent_repository, patient_identity_repository
from server.callbacks.utils.json_file_store import get_all
from server.config import DATABASE_URL
from server.db import init_engine

# Safe to call at import time: none of the three repository modules touch
# the database until one of their functions is actually CALLED (importing
# them only defines session_scope()/ORM class references) -- but this must
# still run before main() calls any save_*() below, same reasoning as
# tools/m3_test_suite/common.py's own init_engine() call.
init_engine(DATABASE_URL)


def _migrate_one(store_file: str, save_fn) -> int:
    rows = get_all(store_file)
    for key, value in rows.items():
        save_fn(key, value)
    return len(rows)


def main() -> None:
    counts = {
        "patient_identities": _migrate_one(
            "patient_identities.jsonl",
            patient_identity_repository.save_patient_identity,
        ),
        "consents": _migrate_one(
            "consents.jsonl",
            consent_repository.save_consent,
        ),
        "hiu_consents": _migrate_one(
            "hiu_consents.jsonl",
            hiu_consent_repository.save_hiu_consent,
        ),
    }

    print("P16 backfill complete -- rows migrated per table:")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    print(
        "\nOriginal .jsonl files under storage/ were NOT modified -- they "
        "remain as an inert audit trail, not the live source of truth."
    )


if __name__ == "__main__":
    main()
