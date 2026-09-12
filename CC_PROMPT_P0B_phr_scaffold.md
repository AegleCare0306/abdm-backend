# Claude Code prompt — P0-B: scaffold `aegle-phr`

> Copy everything below the horizontal rule into Claude Code, running in `C:\Users\hp\Desktop\Aayush\`.
> **Recommended model: Sonnet, extended thinking on.** The design decisions are all made below; execution is well-bounded.

---

You are creating a **new repo** for the PHR (Personal Health Record) app — the patient-facing side of an ABDM integration. This chunk is the scaffold only: no ABDM business flows yet.

## Context you need

Three sibling directories under `C:\Users\hp\Desktop\Aayush\`:

- `repo\` — the existing ABDM backend (HIP + HIU roles). **Read-only for you. Do not modify anything in it.** You'll read `server/config.py` once, for real credential values.
- `aegle-abdm-core\` — a shared package (import name `abdm_core`) built in the previous chunk. **Read-only for you. Do not modify it.** You will install and consume it.
- `aegle-phr\` — **you are creating this.**

Python 3.12, conda env `aegle-care` (already exists, already has the deps). Activate with `conda activate aegle-care`. Both `abdm_core` and `aegle_phr` install into this same env — that is deliberate, because they will eventually run in one process.

## What `abdm_core` gives you

Read its `README.md` first. The parts you need:

```python
from abdm_core.config import configure, GatewayConfig
from abdm_core.paths import configure_paths, StoragePaths
from abdm_core.session import get_gateway_token
from abdm_core.rsa_crypto import get_public_certificate, encrypt_value
from abdm_core.callback_auth import verify_abdm_callback
from abdm_core.http import generate_request_id, generate_timestamp, call_with_retry
from abdm_core.observability.flow_logger import log_phase, log_error
```

Two things about it that shape this task:

1. It has **no module-level side effects and no import-time configuration**. `configure()` and `configure_paths()` must be called explicitly at startup, before anything that talks to ABDM.
2. `get_public_certificate(certificate_url)` takes the **full certificate URL** as an argument. The PHR's is `https://abhasbx.abdm.gov.in/abha/api/v3/phr/app/login/public/certificate` — deliberately different from the existing backend's `.../abha/api/v3/profile/public/certificate`. Do not hardcode either one; it comes from settings.

---

## Design decision 1 — this is a mountable sub-app, not a standalone server

This is the most important constraint in the whole task. The PHR will eventually run **inside the same process** as the existing ABDM backend (one client ID, one callback URL, one ngrok host — so one place for ABDM callbacks to land). Build for that now; retrofitting it later is expensive.

Structure it so the routes are a **router**, and the standalone server is a thin wrapper around that router:

```python
# aegle_phr/api.py
def build_router(settings) -> APIRouter: ...      # all PHR routes, no FastAPI app

# aegle_phr/app.py
def create_app() -> FastAPI: ...                  # thin: bootstrap + include_router + CORS
```

A host application must be able to do exactly this and get working PHR endpoints:

```python
from aegle_phr.bootstrap import bootstrap
from aegle_phr.api import build_router
bootstrap(settings)
app.include_router(build_router(settings))
```

**What this requires of you — treat each as a hard rule:**

- **No module-level side effects anywhere in `aegle_phr`.** No engine created at import. No `configure()` at import. No path resolution at import. No directory creation at import. No settings instantiated at import.
- All setup lives in one **idempotent** `aegle_phr/bootstrap.py:bootstrap(settings)` — calling it twice must be safe and must not create a second engine, because a host app may already have bootstrapped.
- The router must carry **no global state** and no `@app.on_event` handlers. If you need startup work, expose it as a function the host calls.
- Every route path is fully qualified (starts with `/api/v3/...` or `/phr/...`). Do not rely on a mount prefix.

Provide `aegle_phr/__main__.py` so `python -m aegle_phr` runs the standalone server on **port 8001** (the existing backend owns 8000). That's for solo development only.

## Design decision 2 — route handlers are `def`, not `async def`

Everything downstream of a route is **blocking**: `abdm_core` uses `requests`, and SQLAlchemy here is sync. FastAPI runs a plain `def` handler in a threadpool, which is correct and safe. An `async def` handler that then makes a blocking call stalls the event loop for every other request.

The existing backend already hit a real bug of this shape — see its commit `6a1d748`, "Fix event-loop deadlock in M2/M3 self-referential data push". Don't repeat it.

So: **use sync SQLAlchemy (psycopg driver, not asyncpg), and define every route handler as `def`.** Mixing `def` and `async def` routes in one FastAPI app is fine, so this stays compatible when mounted into the existing backend.

## Design decision 3 — configuration comes from `.env`, never from source

The existing `repo\server\config.py` hardcodes `CLIENT_ID` and `CLIENT_SECRET`, and a real secret is already sitting in that repo's git history. This repo must not repeat that.

Use **pydantic-settings**. `aegle_phr/settings.py` defines a `Settings` model with:

| Setting | Notes |
|---|---|
| `abdm_client_id`, `abdm_client_secret` | from `.env` |
| `abdm_gateway_base_url` | e.g. `https://dev.abdm.gov.in/api/hiecm/gateway/v3` |
| `abdm_abha_base_url` | e.g. `https://abhasbx.abdm.gov.in/abha/api/v3` |
| `abdm_hiecm_base_url` | e.g. `https://dev.abdm.gov.in/api/hiecm` |
| `abdm_x_cm_id` | e.g. `sbx` |
| `abdm_callback_url` | the fixed ngrok host |
| `phr_certificate_url` | **full URL**, defaulting to `{abha_base_url}/phr/app/login/public/certificate` |
| `abdm_hiu_id` | the PHR's HIU identifier, sent as `X-HIU-ID`. Leave blank in `.env.example` with a comment that it is not yet confirmed. |
| `database_url` | e.g. `postgresql+psycopg://aegle:aegle@localhost:5433/aegle_phr` |
| `cors_origins` | list; default `["http://localhost:5173"]` |
| `storage_root`, `log_dir` | paths handed to `abdm_core.configure_paths()` |

**Order of operations, and get this right:**

1. Write `.gitignore` **first**, with `.env` in it.
2. Confirm `.env` is actually ignored (`git check-ignore -v .env` — though note there's no git repo here yet, so just verify the pattern is present and correct).
3. Only then create the local `.env`, reading the real values out of `repo\server\config.py`.
4. `.env.example` gets **placeholders only** — never a real credential.

Do not print the real client secret in your final report.

## Design decision 4 — Postgres from day one, via Docker Compose

No `.jsonl` file stores in this repo. The existing backend uses them and they're a known standing caveat; this repo starts on Postgres.

- `docker-compose.yml` running **Postgres 16**, mapped to host port **5433** (not 5432 — avoid colliding with any existing local Postgres), with a named volume so data survives a restart.
- **SQLAlchemy 2.0 declarative style**, sync engine, created inside `bootstrap()`.
- **Alembic** configured, with `alembic.ini` reading the URL from settings rather than hardcoding it.
- One initial migration creating a single table, `callback_log`:
  - `id` (PK), `received_at` (timestamptz, default now), `callback_type` (text), `request_id` (text, nullable), `correlation_id` (text, nullable), `payload` (**JSONB**), `source_ip` (text, nullable)
  - Index on `received_at`, and one on `request_id`.

This table is the PHR's equivalent of the existing backend's callback archive, and it exists in this chunk specifically to prove the DB wiring end-to-end.

## Design decision 5 — which callback paths this repo owns

Register these six, and **only** these six:

```
POST /api/v3/hiu/patient/care-context/on-discover
POST /api/v3/hiu/patient/care-context/on-init
POST /api/v3/hiu/patient/care-context/on-confirm
POST /api/v3/hiu/patient/on-share
POST /api/v3/hiu/hiecm/subscription-requests/on-init
POST /api/v3/hiu/subscription-requests/hiu/notify
```

**Do NOT register these four**, now or ever in this repo without an explicit decision — they are already owned by the existing backend's M3 HIU code, and both apps will share one process:

```
/api/v3/hiu/consent/request/on-init
/api/v3/hiu/consent/request/notify
/api/v3/hiu/consent/on-fetch
/api/v3/hiu/health-information/on-request
```

Put a clear comment block in `aegle_phr/callbacks/router.py` naming these four and why they're absent, so nobody adds them casually later.

In this chunk the six routes are **skeletons**: each applies `Depends(verify_abdm_callback)` from `abdm_core.callback_auth`, writes the payload to `callback_log`, logs via `flow_logger`, and returns the standard ABDM ack. Route them through a single `dispatcher.py` that never raises — a handler failure must not turn into a 500 back to ABDM. Real per-callback handlers come in P3; do not write them now.

Also add `GET /phr/health` returning `{"status": "healthy"}` plus whether the DB is reachable.

---

## Verification — required

There is **no automated test suite anywhere in this project**, so build the verification yourself and show me the actual output.

Offline checks (no network, no sandbox):

1. `docker compose up -d` brings Postgres 16 up on 5433; `alembic upgrade head` succeeds; `callback_log` exists with the right columns and indexes.
2. **Mountability:** in a scratch script, build a bare `FastAPI()`, call `bootstrap(settings)` then `include_router(build_router(settings))`, and assert all seven routes are present on that app. This is the single most important check in this chunk.
3. **No import-time side effects:** import every `aegle_phr` module *without* calling `bootstrap()`, and assert nothing crashes and no DB connection is attempted. Then assert that calling `bootstrap()` twice does not create a second engine.
4. `GET /phr/health` returns 200 with DB reachable true.
5. A POST to one of the six callback routes **without** a valid ABDM JWT returns **401**, not 200 and not 500.
6. A POST *with* verification bypassed (monkeypatch the dependency) writes exactly one `callback_log` row with the payload intact as JSONB.
7. Confirm the four forbidden paths are **not** registered — assert they 404.

Then one **live sandbox check**, which is the real point of this chunk — it proves `abdm_core`'s config injection and per-URL certificate handling work against the real thing:

8. Call `get_gateway_token()` and confirm a token comes back.
9. Call `get_public_certificate(settings.phr_certificate_url)` and confirm a public key comes back from the **PHR** certificate endpoint. Report whether that key is identical to the one at the existing backend's `.../profile/public/certificate` endpoint — this is currently an open question and a real answer either way is useful. **Report what you observe; do not assume they match.**

Delete the verification scripts once they pass. Leave `docker-compose.yml`, migrations, and `.env` in place.

Write a short `README.md` covering: what this repo is, the one-command dev startup, how to run standalone vs. mounted, and an explicit note that the four consent/data-flow callback paths are deliberately not owned here.

---

## Ground rules — these apply to every task in this project

1. **No throwaway scripts left behind.** Delete scratch/verification scripts once they've served their purpose.
2. **Detailed per-file change report at the end** — exactly what changed, where, and why. Plus a short summary I can paste back into my Cowork session for review.
3. **Strict scope discipline.** Change nothing beyond what this prompt specifies. If you spot a bug outside this scope, *flag it, don't fix it*. If you introduce a bug yourself while doing the assigned work, fix that one.
4. **No git commit, no git push, no `git init`.** Leave everything as uncommitted working-tree state. Reviewing and committing is my job.
5. **Never overwrite real output data.** Back up anything you might touch under `logs/` or `storage/`, restore it exactly afterward. Never delete or truncate existing logs or storage.
6. **Don't claim something works without running it.** "Should work" is not verification.
7. **Flag uncertainty visibly.** If a payload shape, spec detail, or API behaviour is unconfirmed, say so plainly rather than presenting a guess as fact.
8. **Do not modify `repo\` or `aegle-abdm-core\`.** If either genuinely needs a change, stop and tell me instead of making it.
