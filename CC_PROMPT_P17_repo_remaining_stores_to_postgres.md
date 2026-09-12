# P17 — Finish moving `repo/`'s file-backed stores to Postgres, plus one small P16 follow-up fix

Aayush's own instruction (2026-09-07): P16 (the security-critical trio — `hiu_consent_repository.py`,
`consent_repository.py`, `patient_identity_repository.py`) is confirmed run and verified. Two things now:
(1) fix a small gap Cowork found while re-verifying P16, (2) move the rest of `repo/`'s file-backed
repository modules to the same Postgres setup P16 already built — no new database, no new Alembic chain,
reuse everything P16 already created.

**Model recommendation: Sonnet, extended thinking ON.** Same reasoning as P16 — this touches storage
behind several live-tested flows (HIP-Initiated Linking, Data Flow, M3 Consent/Health-Information), and a
couple of the modules here have real behavioral subtleties (a merge instead of an overwrite, a two-file
index pattern, a "falsy" filter) that are easy to flatten into something simpler-but-wrong if rushed.

## Part A — small fix: aegle-phr's solo-dev standalone server never initialises repo/'s new DB engine

**Background, so this isn't done blind:** P16 added `server/db.py` + `init_engine()`, and
`repo/server/main.py`'s own startup already calls it — so the real, documented deployment (aegle-phr
mounted into `repo/server/main.py`, port 8000) has always worked correctly since P16 shipped. While
re-verifying P16, Cowork found that `aegle_phr/phr/data_flow.py` calls straight into THREE of `repo/`'s
repository modules directly from `aegle_phr`'s own code (`hiu_consent_repository`,
`hiu_health_information_repository`, `pending_health_information_request_repository` — grep confirmed all
three, e.g. `discover_self_view_consents()`, `get_health_information_status()`), not just from files under
`server/`. That's fine in the real mounted deployment (same process, engine already initialised at
startup) — but `aegle_phr` also ships its own "FOR SOLO DEVELOPMENT ONLY" standalone server
(`aegle_phr/app.py` + `aegle_phr/__main__.py`, `python -m aegle_phr`, port 8001), and that entrypoint's
`bootstrap()` only initialises `aegle_phr`'s OWN database engine — never `repo/`'s. `aegle_phr/phr/
data_flow.py`'s own error message already documents this combination isn't really supported ("Data Flow
only works when aegle_phr is mounted into repo/server/main.py ... not when run standalone via
aegle_phr.app:create_app (dev-only)") — so this is a real gap, but a low-stakes one; fix it anyway since
it's one line and makes the standalone server's failure mode correct (an explicit, early error) instead of
whatever `RuntimeError` shape `server/db.py`'s `get_engine()` raises when nobody bootstrapped it.

**The fix:** in `aegle_phr/app.py`'s `create_app()` (or `aegle_phr/bootstrap.py`'s `bootstrap()` — pick
whichever this codebase's own convention says configuration-time setup belongs in, they already have one),
add:

```python
try:
    from server.db import init_engine
    from server.config import DATABASE_URL
    init_engine(DATABASE_URL)
except ImportError:
    pass  # repo/'s server package isn't installed/importable — standalone mode already handles this
          # per-call via its own try/except ImportError blocks; nothing else to do here.
```

Wrap it in `try/except ImportError`, matching every other place `aegle_phr` reaches into `repo/`'s package
— `aegle_phr` must still start up fine on a machine that doesn't have `repo/`'s server package at all.
`init_engine()` is idempotent (confirmed in P16 — safe to call twice), so this is safe even though the
mounted deployment already calls it separately; the two code paths never run in the same process.

## Part B — the remaining file-backed repository modules

`repo/server/callbacks/repository/` has 13 modules total. P16 did the security-critical 3. This does 9 of
the remaining 10. One is deliberately excluded — read why before assuming it was missed.

**In scope, 9 modules:**

1. `care_context_link_repository.py` — `storage/pending_care_context_links.jsonl` — simple key/value
   (save/get/delete), key = REQUEST-ID.
2. `care_context_notify_repository.py` — `storage/pending_care_context_notifies.jsonl` — same shape, key
   = REQUEST-ID.
3. `link_repository.py` — `storage/link_sessions.jsonl` — key/value plus `update_link_session()` (a
   read-modify-write full replace, not a partial merge — `session.update(updated_data)` on a copy, then a
   full `set_key()`), `link_session_exists()`, `get_all_link_sessions()`, `clear_all_link_sessions()` (no
   caller today — implement as a real bulk `DELETE`, not a loop of tombstone-appends; the "no true
   truncate" limitation it works around no longer applies).
4. `link_token_repository.py` — `storage/pending_link_tokens.jsonl` — simple key/value, key = REQUEST-ID.
5. `patient_link_token_repository.py` — `storage/patient_link_tokens.jsonl` — key/value, but the key is
   already a composite string built by `_composite_key(abha_address, hip_id)` → `f"{abha_address}|{hip_id}"`.
   Keep that exact composite-string as the unique key column (don't split into two columns + a composite
   unique constraint — that's a real improvement but a bigger redesign than this chunk needs; a future
   cleanup can normalize it).
6. `pending_consent_request_repository.py` — TWO files: `storage/pending_consent_requests.jsonl` (key =
   our own REQUEST-ID) and `storage/pending_consent_requests_by_consent_request_id.jsonl` (key = ABDM's
   `consentRequestId`, value = the REQUEST-ID string it maps to — a plain string value, not an object).
   See "two-file index pattern" below.
7. `pending_health_information_request_repository.py` — same two-file index pattern: `storage/
   pending_health_information_requests.jsonl` (key = our REQUEST-ID) + `storage/
   pending_health_information_requests_by_transaction_id.jsonl` (key = ABDM's `transactionId`, value = the
   REQUEST-ID string). Also has `get_unlinked_pending_health_information_requests()` — see "falsy filter"
   below.
8. `hiu_health_information_repository.py` — `storage/hiu_health_information.jsonl`, key = `transactionId`.
   **Different in one respect from everything migrated so far**: this file is 14.9 MB across only 118 live
   keys (~127 KB average payload — full FHIR bundles per transaction, not small metadata dicts like P16's
   trio). Postgres JSONB handles a payload this size with no special handling needed (TOAST storage is
   automatic) — flagging only so the backfill script isn't written assuming every row is small, and so
   nobody's surprised the migration touches noticeably more data than P16 did despite a similar row count.
9. `health_information_repository.py` — **not file-backed at all today**, unlike every other module in
   this list — it's a plain in-memory module-level dict (`_health_information_sessions = {}`), lost on
   every restart, invisible across OS processes. Migrating this to Postgres is a genuine behavior change,
   not a pure storage-backend swap — flag this explicitly in your own report rather than describing it the
   same way as the other 8. Two things to get right: (a) there's nothing to backfill (the in-memory dict is
   always empty at the moment this runs — the table just starts empty, no migration script needed for this
   one); (b) `update_health_information_session(transaction_id, updated_data)` currently does a **partial
   merge** (`_health_information_sessions[transaction_id].update(updated_data)`), not an overwrite — the
   Postgres version must preserve that merge semantics (e.g. `UPDATE ... SET data = data || :updated_data
   ::jsonb, updated_at = now() WHERE key = :transaction_id`, using Postgres's JSONB `||` concat operator
   for a shallow merge, matching Python `dict.update()`'s shallow-merge behavior) — do NOT implement this
   as a full replace, that would silently drop whatever fields the caller didn't include in `updated_data`.

**Excluded from this chunk, on purpose — not an oversight:**

- **`patient_repository.py`** — this is NOT a key/value session store like the other 12. It's a CSV reader
  against `server/data/patient_records.csv`, the dummy EMR fixture data generated by `tools/
  generate_dummy_emr.py` / `tools/generate_patient_records.py`. Migrating this would mean also touching
  those generator scripts and deciding how test-fixture data relates to a real database — a different,
  unrelated piece of work from "move runtime consent/session state off fragile files." Leave it exactly as
  it is.
- **`server/callbacks/utils/idempotency.py`** (`storage/processed_callback_request_ids.jsonl`) — this
  isn't one of the 13 repository modules at all; it's a small cross-cutting dedup/idempotency guard used by
  `consent_notify_service.py` (and designed to be reused by other callback handlers later, not yet wired
  up everywhere). Structurally it's the same append-only key/value pattern, so it COULD move the same way
  — but it's conceptually a different kind of thing (a system-wide guard, not domain data) and moving it
  wasn't part of what Aayush asked for. Flagging it here as a candidate for its own small follow-up later,
  not migrating it now.

## Two-file index pattern (modules 6 and 7 above) — keep as two tables, don't collapse into one

Both `pending_consent_request_repository.py` and `pending_health_information_request_repository.py` use
the identical shape, for the identical reason (their own docstrings explain it): the callback that carries
ABDM's real id (`consentRequestId` / `transactionId`) arrives separately from — and later than — the
original outbound call, so a second file indexes that real id back to the REQUEST-ID the session was
originally saved under, rather than duplicating the whole record under two keys. Preserve this as **two
separate tables per module** (a main table + an index table), matching P16's own rule of keeping stores
"exactly as separate as the files were" — don't merge the index into the main table as a second unique
column, that's a reasonable future cleanup but changes the shape more than this chunk needs.

- Main table (e.g. `pending_consent_requests`): `id` bigserial PK, `request_id` text UNIQUE NOT NULL, `data`
  JSONB NOT NULL, `created_at`/`updated_at` timestamptz. Same for `pending_health_information_requests`
  with the same shape.
- Index table (e.g. `pending_consent_requests_by_consent_request_id`): `id` bigserial PK,
  `consent_request_id` text UNIQUE NOT NULL, `request_id` text NOT NULL, `created_at` timestamptz. Same
  for `pending_health_information_requests_by_transaction_id` (`transaction_id` → `request_id`). Note the
  index tables' stored value in the OLD files is a bare string (the REQUEST-ID), not a JSON object — a
  plain `request_id text` column is the right fit, don't wrap it in a JSONB column just for consistency
  with the other tables.

`link_consent_request_id()` / `link_transaction_id()` write to BOTH tables in one call today (merge the
real id into the main record's `data`, AND write the index row) — preserve that as a single transaction
(both writes commit together or neither does), so the two tables can't drift out of sync the way two
independent unguarded writes could.

## Falsy filter — `get_unlinked_pending_health_information_requests()`

Today: `{request_id: session for request_id, session in all_sessions.items() if not session.get
("transaction_id")}` — Python's `not x` treats `None`, missing key, and empty string `""` all as "not
linked yet." The Postgres query needs the same three-way falsy check, not just `IS NULL` — e.g. `WHERE
data->>'transaction_id' IS NULL OR data->>'transaction_id' = ''`. A query that only checks `IS NULL` would
silently stop matching a session whose `transaction_id` field exists but is an empty string, changing this
function's behavior in a way nothing currently in this codebase would notice until it happened live.

## Standalone CLI callers needing their own engine init — found by checking, not assumed absent

P16 found and fixed `tools/m3_test_suite/common.py` (a standalone CLI, separate OS process from the
FastAPI server). Checking again for THIS chunk's modules specifically (don't just trust that P16's fix
covers everything): **`tools/m2_test_suite/cli.py` is the same situation** — its own `if __name__ ==
"__main__":` entrypoint, and its `common.py` currently has no `init_engine()` call at all. `tools/
m2_test_suite/flows/hip_linking.py` (reached from this CLI) directly imports from `link_token_repository`,
`patient_link_token_repository`, `care_context_link_repository`, `care_context_notify_repository`, and
`link_repository` — all five in this chunk's scope. Without this fix, running the M2 test CLI after this
migration would break exactly the way M3's CLI would have broken without P16's fix.

**The fix — mirror `tools/m3_test_suite/common.py`'s own P16 fix exactly** (same file even has a
comment already explaining why, dated "P16" — read it for the full reasoning, don't just copy blindly):
add, near the top of `tools/m2_test_suite/common.py`, before any repository import:

```python
from server.config import DATABASE_URL
from server.db import init_engine

init_engine(DATABASE_URL)
```

placed before the `from server.callbacks.repository.patient_repository import search_patient` line
already there, so it runs first at import time. (Also double-check `tools/m2_test_suite/flows/
hip_linking.py` doesn't import any of these five repositories in a path that could somehow execute before
`common.py`'s import — Python resolves this correctly as long as the init call is at module level in a
file that gets imported before any repository function is actually CALLED, which it will be here, but
verify rather than assume.)

## Backfill

New script, `tools/migrate_remaining_repo_stores_to_postgres.py` (separate from P16's own migration
script — this is phase 2, keep phase 1's script untouched as a record of what it did). For each of the 8
file-backed modules in scope (everything above except `health_information_repository.py`, which has
nothing to backfill), read every existing key via the module's EXISTING `json_file_store.get_all()` (same
discipline as P16 — reuse it, don't hand-parse the `.jsonl` files) and upsert into the new tables. Expected
row counts, so you can sanity-check the backfill actually worked rather than silently migrating zero rows:
`pending_care_context_links` ~3, `pending_care_context_notifies` ~0 (all currently deleted/tombstoned —
zero is correct here, don't treat it as a bug), `link_sessions` ~12, `pending_link_tokens` ~4,
`patient_link_tokens` ~5, `pending_consent_requests` ~153 / its index table ~63, `pending_health_
information_requests` ~146 / its index table ~125, `hiu_health_information` ~118. Print a summary (rows
migrated per table), same as P16's script did. **Do not delete or truncate any of the original `.jsonl`
files** — standing rule, unchanged.

## Alembic

Reuse the SAME independent Alembic chain P16 already created in `repo/` — do NOT create a second chain or
touch `aegle_phr`'s own chain. Add new migration files to the existing `alembic/versions/` directory for
the new tables (`pending_care_context_links`, `pending_care_context_notifies`, `link_sessions`,
`pending_link_tokens`, `patient_link_tokens`, `pending_consent_requests`, `pending_consent_requests_by_
consent_request_id`, `pending_health_information_requests`, `pending_health_information_requests_by_
transaction_id`, `hiu_health_information`, `health_information_sessions`) — confirm none of these names
collide with anything `aegle_phr`'s own chain already created (same check P16 did for its own three
tables).

## Verification

Offline: read every changed/new file back. Confirm every call site outside these repository files still
works unchanged — Part A's fix should mean this is now also true for `aegle_phr`'s standalone mode, not
just the mounted deployment. Confirm the backfill script actually ran and each table's row count matches
`get_all()`'s pre-migration count. Confirm `tools/m2_test_suite/common.py`'s new init call mirrors `tools/
m3_test_suite/common.py`'s exactly (same DATABASE_URL source, same idempotent `init_engine()` call).

Live (ask before each step): 1. Start the server, confirm `/health` still reports healthy. 2. Re-run HIP-
Initiated Linking end-to-end for a patient (exercises `link_token_repository`, `patient_link_token_
repository`, `care_context_link_repository`, `care_context_notify_repository`, `link_repository` all in
one flow) — confirm it still succeeds identically post-migration; this is the regression check that
actually matters for this chunk's biggest cluster of modules. 3. Re-run a Data Flow fetch for a patient
with existing decrypted data (`hiu_health_information_repository`, `pending_health_information_request_
repository`) — confirm `get_health_information_status()` and the actual fetched content still work
post-migration. 4. Run the M2 test CLI (`tools/m2_test_suite/cli.py`) standalone and confirm it works —
this is the check that Part A's cousin-fix (this section's own CLI fix, not Part A's aegle-phr fix) landed
correctly.

## Constraints (standing, unchanged)

Never delete/truncate `logs/`/`storage/` content. No git commit/push/init. Never print the access key,
client secret, plaintext OTP, mobile number, email address, password, or any live token into any report.
