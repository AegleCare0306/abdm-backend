"""
One-time backfill (P17, 2026-09-07): phase 2 of moving repo/'s file-backed
stores to Postgres -- see tools/migrate_consent_stores_to_postgres.py
(phase 1, P16, kept untouched as a record of what it did) for the same
pattern applied to the three security-critical stores.

Covers the 8 of the 9 P17-scope modules that were actually file-backed
(everything except health_information_repository.py, which replaced an
IN-MEMORY dict -- always empty at migration time, nothing to backfill for
that one). Two of these eight are TWO-FILE index-pattern modules
(pending_consent_request_repository.py, pending_health_information_
request_repository.py) -- both the main store and its index file are
backfilled here, into their own separate tables.

Run ONCE, after `alembic upgrade head` has created the target tables:
`python -m tools.migrate_remaining_repo_stores_to_postgres` from the repo
root.

Reads via the EXISTING server/callbacks/utils/json_file_store.py's own
get_all() -- same discipline as phase 1, reused rather than re-parsing the
.jsonl files by hand. Writes via each repository module's own save_*()-
shaped upsert logic -- for the two index-pattern modules, the index
file's stored value is a bare string (the REQUEST-ID), not an object, so
those two go through a small local upsert helper rather than a
module-level save_*() function (neither repository module exposes one for
its index table alone -- link_consent_request_id()/link_transaction_id()
do both writes together, which needs a real pending row to attach to,
not just a backfill row).

DOES NOT delete or truncate any of the original .jsonl files -- standing
rule, also just sensible here: they become an inert audit trail after
cutover, not the live source of truth anymore. Safe to re-run -- every
write here is an upsert, so running this script twice just re-applies the
same rows.
"""

from server.callbacks.repository import (
    care_context_link_repository,
    care_context_notify_repository,
    hiu_health_information_repository,
    link_repository,
    link_token_repository,
    patient_link_token_repository,
    pending_consent_request_repository,
    pending_health_information_request_repository,
)
from server.callbacks.utils.json_file_store import get_all
from server.config import DATABASE_URL
from server.db import init_engine, session_scope
from server.db_models import PendingConsentRequestByConsentRequestId, PendingHealthInformationRequestByTransactionId

from sqlalchemy.dialects.postgresql import insert as pg_insert

# Safe to call at import time -- see tools/migrate_consent_stores_to_postgres.py's
# own comment on this same call for why (none of these repository modules
# touch the database until a function is actually called).
init_engine(DATABASE_URL)


def _migrate_one(store_file: str, save_fn) -> int:
    rows = get_all(store_file)
    for key, value in rows.items():
        save_fn(key, value)
    return len(rows)


def _migrate_index_file(store_file: str, table, key_column, value_column) -> int:
    """
    For the two index files whose stored value is a bare string (the
    REQUEST-ID), not a JSON object -- upserts directly against the index
    table's own two text columns, since neither repository module exposes
    a save-the-index-row-alone function (their own link_*() functions do
    both writes together against a real pending row, which a backfill
    doesn't have -- it's just replaying what the index file already
    recorded).
    """
    rows = get_all(store_file)
    with session_scope() as session:
        for key, value in rows.items():
            stmt = pg_insert(table).values(**{key_column: key, value_column: value})
            stmt = stmt.on_conflict_do_update(
                index_elements=[getattr(table, key_column)],
                set_={value_column: stmt.excluded[value_column]},
            )
            session.execute(stmt)
    return len(rows)


def main() -> None:
    counts = {
        "pending_care_context_links": _migrate_one(
            "pending_care_context_links.jsonl",
            care_context_link_repository.save_pending_care_context_link,
        ),
        "pending_care_context_notifies": _migrate_one(
            "pending_care_context_notifies.jsonl",
            care_context_notify_repository.save_pending_care_context_notify,
        ),
        "link_sessions": _migrate_one(
            "link_sessions.jsonl",
            link_repository.save_link_session,
        ),
        "pending_link_tokens": _migrate_one(
            "pending_link_tokens.jsonl",
            link_token_repository.save_pending_link_token,
        ),
        # patient_link_tokens.jsonl's own stored value is ALREADY the
        # {link_token, hip_id, received_at} dict save_patient_link_token()
        # would normally build itself from (abha_address, link_token,
        # hip_id) arguments -- writing it straight into the table's own
        # data column via the same upsert shape, not through that
        # function (which would double-wrap it), keeps this an honest
        # replay of what the file already held.
        "patient_link_tokens": _migrate_one(
            "patient_link_tokens.jsonl",
            lambda composite_key, data: _upsert_patient_link_token(composite_key, data),
        ),
        "pending_consent_requests": _migrate_one(
            "pending_consent_requests.jsonl",
            pending_consent_request_repository.save_pending_consent_request,
        ),
        "pending_consent_requests_by_consent_request_id": _migrate_index_file(
            "pending_consent_requests_by_consent_request_id.jsonl",
            PendingConsentRequestByConsentRequestId,
            "consent_request_id",
            "request_id",
        ),
        "pending_health_information_requests": _migrate_one(
            "pending_health_information_requests.jsonl",
            pending_health_information_request_repository.save_pending_health_information_request,
        ),
        "pending_health_information_requests_by_transaction_id": _migrate_index_file(
            "pending_health_information_requests_by_transaction_id.jsonl",
            PendingHealthInformationRequestByTransactionId,
            "transaction_id",
            "request_id",
        ),
        "hiu_health_information": _migrate_one(
            "hiu_health_information.jsonl",
            hiu_health_information_repository.save_hiu_health_information,
        ),
    }

    print("P17 backfill complete -- rows migrated per table:")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    print(
        "\nhealth_information_sessions: 0 (nothing to backfill -- replaced an "
        "in-memory dict, always empty at migration time, not a file)."
    )
    print(
        "\nOriginal .jsonl files under storage/ were NOT modified -- they "
        "remain as an inert audit trail, not the live source of truth."
    )


def _upsert_patient_link_token(composite_key: str, data: dict) -> None:
    from sqlalchemy import func

    from server.db_models import PatientLinkToken

    with session_scope() as session:
        stmt = pg_insert(PatientLinkToken).values(composite_key=composite_key, data=data)
        stmt = stmt.on_conflict_do_update(
            index_elements=[PatientLinkToken.composite_key],
            set_={"data": stmt.excluded.data, "updated_at": func.now()},
        )
        session.execute(stmt)


if __name__ == "__main__":
    main()
