# P16 — Move `repo/`'s consent/identity stores off JSONL files, onto Postgres

Aayush's own instruction (2026-09-05): stop depending on file-based local state in `repo/` at all —
move the data that actually matters into a real database so it isn't tied to "the system" (this one
process's local files) anymore. This came up from a real question: if his team links a record through
a different system/registration than this one, `aegle-phr` currently can't retrieve it, because
`repo/`'s own consent-usability check is gated on a **local file cache** that only records what THIS
registration itself raised and fetched. Moving that state to Postgres does not remove that gate (see
"What this does NOT change" below, please read it before touching anything) — it just stops the gate
from living in a fragile per-process file.

**Model recommendation: Sonnet, extended thinking ON.** This touches the one piece of `repo/`'s design
that's been directly responsible for a real security property (no cross-registration consent reuse),
proven live and repeatedly throughout this project. Behavior preservation matters more than speed here.

**Scope, deliberately narrow — this is phase 1 of a bigger cleanup, not all of it.** `repo/` has 13
file-backed repository modules under `server/callbacks/repository/`. This chunk only moves THREE of
them — the security-critical trio:

1. `hiu_consent_repository.py` (`storage/hiu_consents.jsonl`) — consents WE fetched acting as an HIU.
   This is the one `hiu_health_information.py`'s fetch-gate reads (`get_hiu_consent(consent_id)`), and
   it's the module actually enforcing "a consent from a different registration can never be used here."
2. `consent_repository.py` (`storage/consents.jsonl`) — consents WE received notification of acting as
   an HIP.
3. `patient_identity_repository.py` (`storage/patient_identities.jsonl`) — patient identity resolved by
   Discover, consumed by Link Init/Confirm.

The other 10 (links, tokens, notifies, health-information-request tracking) stay on JSONL for now —
a later chunk, once this one is confirmed working.

## What this does NOT change — read this before writing any code

The actual safety property is: `get_hiu_consent(consent_id)` returns a row **only if THIS repo's own
`hiu_consent.py` flow itself fetched that specific consent** — a consent raised through a different
app/registration is structurally absent, full stop, regardless of what ABDM itself thinks its status is.
That's not a side effect of file storage — it's the whole point of a local cache keyed by "did we
ourselves put this here." **Moving to Postgres must preserve this exactly**: `save_hiu_consent()` is
still only ever called from the same one place it is today (`consent_hiu_on_fetch_service.py`, after a
real on-fetch callback for a consent OUR OWN registration requested), and `get_hiu_consent()` still
returns `None` for anything nobody on this side of the fence ever wrote. If you find yourself writing
code that makes a foreign/ABDM-visible consent become readable here just because it's now "in the
database," you've changed the actual security model, not just its storage backend — stop and flag it
rather than proceeding. (Separately, if Aayush wants a DIFFERENT chunk later that intentionally lets a
consent raised by any of his team's own systems be usable across all of them, that's a real, bigger
design conversation — cross-registration trust, not a storage swap — and should go through Cowork as
its own explicit decision, not get bundled into this one silently.)

## Why Postgres, and which one

`aegle-phr` already runs the only Postgres instance in this project — `docker-compose.yml` in
`aegle-phr/`, Postgres 16 on host port 5433, database `aegle_phr`, already holding `callback_log`,
`abdm_call_log`, `subscription_request`, `uil_link_request`. `repo/`'s own `main.py` already mounts
`aegle_phr`'s router into the same process — there's no reason to stand up a second database; point
these three new tables at that exact same instance (new `DATABASE_URL` entry in `repo/`'s own `.env`,
same value `aegle_phr/.env` uses: `postgresql+psycopg://aegle:aegle@localhost:5433/aegle_phr`). Table
names `hiu_consents`, `consents`, `patient_identities` don't collide with any existing `aegle_phr` table
— confirmed directly against `aegle_phr/models.py`.

**Do NOT import anything from `aegle_phr` or `aegle_abdm_core` to do this.** `repo/server/main.py`'s own
comment is explicit: aegle-phr and aegle-abdm-core "must not become hard dependencies" of `repo/`, wrapped
in `try/except ImportError` specifically so `repo/` still runs standalone without either installed. Reusing
`aegle_phr.db`'s already-bootstrapped engine would violate that outright — and `tools/m3_test_suite/
common.py` calls `get_all_hiu_consents()` as a standalone CLI script that never goes through `aegle_phr`'s
bootstrap at all, so it couldn't reach that engine even if the dependency were acceptable. Instead: give
`repo/` its own small, self-contained DB module (new `server/db.py`), mirroring `aegle_phr/db.py`'s proven
pattern (sync SQLAlchemy/psycopg, idempotent `init_engine()`, `session_scope()` context manager, a
`check_connection()` for `/health`) but entirely independent of it — copy the pattern, don't import the
module. `aegle-abdm-core` is where P0-D (still not done, unrelated to this) will eventually consolidate
shared code — don't fold this into that refactor now, it's a separate, larger, already-deferred task.

**Real consequence, worth saying plainly**: this makes `repo/` require a reachable Postgres to start up
correctly, even in the "aegle-phr not installed" standalone mode the try/except above exists for — it
didn't need any external service before. In practice this Postgres container is already running on this
machine for `aegle-phr`'s own sake, so it's not new infrastructure to stand up, just a new thing `repo/`
itself now depends on. Flagging this because it's a real, deliberate change to `repo/`'s standalone
story, not because there's a way around it given what Aayush asked for.

## Schema, one table per store — keep them exactly as separate as the files were

Same reasoning `hiu_consent_repository.py`'s own docstring already gives for not merging with
`consent_repository.py` ("merging them risks one role's code misreading the other's data") — three
separate tables, not one shared key-value table:

- `patient_identities` — `id` bigserial PK, `abha_address` text UNIQUE NOT NULL (the key), `data` JSONB
  NOT NULL, `created_at`/`updated_at` timestamptz.
- `consents` — `id` bigserial PK, `consent_id` text UNIQUE NOT NULL (the key), `data` JSONB NOT NULL,
  `created_at`/`updated_at` timestamptz.
- `hiu_consents` — same shape as `consents`, `consent_id` text UNIQUE NOT NULL, `data` JSONB NOT NULL,
  `created_at`/`updated_at` timestamptz.

No Alembic exists in `repo/` today — add a new, independent one (own `alembic.ini`, own `alembic/
versions/`, pointed at the same `DATABASE_URL`). This is a separate migration history from `aegle_phr`'s
own — that's fine, Postgres doesn't care that two different Alembic chains manage different tables in
the same database, as long as they don't touch each other's tables (confirmed no name collision above).

## Function-level behavior to preserve exactly (call sites must not need to change)

Every caller of these three modules imports plain functions (`save_hiu_consent`, `get_hiu_consent`,
`delete_hiu_consent`, `get_all_hiu_consents`, and the equivalents for the other two) — nobody outside
the three repository files touches `json_file_store.py` directly. Keep every function's name, signature,
and return contract byte-for-byte identical:
- `save_*(key, data)` — upsert (INSERT ... ON CONFLICT (key column) DO UPDATE SET data = excluded.data,
  updated_at = now()). Matches `set_key()`'s "always overwrites, no merge" behavior.
- `get_*(key)` — returns the stored dict, or `None` if no row exists. A JSONB column deserializes to a
  fresh Python dict per query, so the existing `deepcopy()` calls in the current code (there to stop a
  caller's mutation from corrupting a cached/shared object) are no longer doing anything meaningful —
  fine to drop them, but double check nothing subtle relied on the exact object identity (it shouldn't).
- `delete_*(key)` — a real `DELETE ... WHERE key = :key`, returning `True` if a row actually existed
  and was removed, `False` otherwise (check the delete's row count — this is simpler and more correct
  than the file version's tombstone-append trick, which only existed to work around append-only files).
- `get_all_*()` — `SELECT key, data FROM table` → `{key: data}` dict. Debugging helper only
  (`tools/m3_test_suite/common.py` is the one real caller) — no pagination needed at today's row counts.

**Standalone CLI callers need their own engine init.** `tools/m3_test_suite/common.py` and
`tools/m3_test_suite/cli.py` run as a separate process from the FastAPI server and currently work
against these files with zero setup. Once these repositories are DB-backed, that CLI needs to call the
new `server/db.py`'s `init_engine(DATABASE_URL)` once at its own startup (reading `DATABASE_URL` the
same way `server/main.py` will) before any repository call — find every such standalone entrypoint that
touches these three modules (grep confirmed `tools/m3_test_suite/common.py` is the only one outside
`server/`) and add that init call there, not just in `server/main.py`.

## Existing data must not just vanish

`storage/hiu_consents.jsonl`, `storage/consents.jsonl`, and `storage/patient_identities.jsonl` currently
hold real, live consent/identity state this project depends on for things that already work (e.g.
Data Flow's self-view fetch reads real rows in `hiu_consents.jsonl` today). Write a one-time backfill
script (e.g. `tools/migrate_consent_stores_to_postgres.py`) that reads every key via the EXISTING
`json_file_store.get_all()` (already correct — reuse it, don't re-parse the `.jsonl` files by hand) and
upserts each into the new tables, run once before cutting the repository modules over. Print a summary
(rows migrated per table). **Do not delete or truncate the original `.jsonl` files** — standing rule,
also just sensible here: they become an inert audit trail after cutover, not the live source of truth
anymore.

## Verification

Offline: read every changed/new file back. Confirm `hiu_health_information.py`'s and
`health_information_hiu_push_service.py`'s calls to `get_hiu_consent()` didn't need to change at all
(only the repository's internals did). Confirm the backfill script actually ran and the row counts in
Postgres match `get_all()`'s count from the old files before cutover. Confirm `tools/m3_test_suite/
common.py` still works standalone with its own new init call.

Live (ask before each step): 1. Start the server, confirm `/health` still reports healthy with the new
DB dependency reachable. 2. Re-run an existing, already-proven-working self-view fetch for a patient
whose `hiu_consents.jsonl` row got migrated — confirm it still succeeds identically post-migration
(this is the regression check that actually matters). 3. Re-run the "foreign PATRQT consent fails
cleanly" check (a consent NOT in the migrated data, e.g. from ABDM's own sandbox app) — confirm it still
fails with the same clean "no local record of consent" error, not a new one. This is the one test that
proves the security property survived the migration, not just the happy path.

## Constraints (standing, unchanged)

Never delete/truncate `logs/`/`storage/` content. No git commit/push/init. Never print the access key,
client secret, plaintext OTP, mobile number, email address, password, or any live token into any report.
