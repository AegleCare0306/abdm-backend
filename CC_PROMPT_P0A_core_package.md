# Claude Code prompt — P0-A: create `aegle-abdm-core` (chunk 1)

> Copy everything below the line into Claude Code, running in `C:\Users\hp\Desktop\Aayush\`.
> **Recommended model: Opus, extended thinking on.** Reason in the Cowork summary.

---

You are creating a **new, standalone Python package** called `aegle-abdm-core` that will be shared by two applications: the existing ABDM backend (`C:\Users\hp\Desktop\Aayush\repo`) and a new PHR app being built next.

## Critical scope rule for this task

**Do not modify a single file inside `C:\Users\hp\Desktop\Aayush\repo`.** That repo is working, tested against the real ABDM sandbox, and must stay exactly as it is. You are **reading from it and copying out of it**. The refactor that points it at this new package is a separate, later task. If you find yourself editing anything under `repo\`, stop — you've misread the task.

## Where things go

- New package root: `C:\Users\hp\Desktop\Aayush\aegle-abdm-core\`
- Import name: `abdm_core`
- Source repo to copy from (read-only): `C:\Users\hp\Desktop\Aayush\repo\`
- Python 3.12, conda env `aegle-care` (already exists and has the deps — activate it with `conda activate aegle-care`)

## What this package is for

It holds the ABDM plumbing that is genuinely identical no matter which role you're playing (HIP, HIU, or PHR): gateway session tokens, the retry wrapper, request-id/timestamp generation, RSA encryption of Aadhaar/OTP/password values, the Fidelius ECDH/AES-GCM health-data crypto, verification of inbound ABDM callback JWTs, and logging/capture.

It must contain **no role-specific knowledge** — no HIP endpoints, no PHR endpoints, no FHIR builders, no business logic.

---

## Modules to create in this chunk

Copy the source file, then apply the change described. Preserve every existing docstring and comment — they encode a lot of hard-won debugging knowledge (tracker case references, race-condition explanations, retry classification rationale). Do not "clean them up" or shorten them.

| New file | Copy from | Change |
|---|---|---|
| `abdm_core/config.py` | *(new)* | see **Design decision 1** |
| `abdm_core/paths.py` | *(new)* | see **Design decision 2** |
| `abdm_core/http.py` | `server/utils.py` | everything **except** `get_gateway_token()` |
| `abdm_core/session.py` | `server/utils.py:get_gateway_token()` + `server/auth.py:generate_gateway_token()` | see **Design decision 1** |
| `abdm_core/rsa_crypto.py` | `server/crypto.py` | see **Design decision 3** |
| `abdm_core/fidelius.py` | `server/fidelius_crypto.py` | none — copy verbatim |
| `abdm_core/callback_auth.py` | `server/callbacks/utils/jwt_auth.py` | see **Design decision 4** |
| `abdm_core/observability/logger.py` | `server/callbacks/utils/logger.py` | none |
| `abdm_core/observability/flow_logger.py` | `server/callbacks/utils/flow_logger.py` | see **Design decision 2** |
| `abdm_core/observability/api_capture.py` | `server/callbacks/utils/api_capture.py` | see **Design decision 2** |

Nothing else moves in this chunk. `idempotency.py`, `response.py`, `storage.py`, `json_file_store.py` and the FHIR helpers are deliberately deferred to a later chunk — do not bring them across.

---

## Design decision 1 — configuration is injected, not imported

Today `server/utils.py`, `server/auth.py`, `server/crypto.py` and `server/callbacks/utils/jwt_auth.py` all do `from server.config import ...`. The package obviously cannot do that.

Create `abdm_core/config.py` with a frozen dataclass and a module-level configure/get pair:

```python
@dataclass(frozen=True)
class GatewayConfig:
    client_id: str
    client_secret: str
    gateway_base_url: str
    x_cm_id: str

def configure(config: GatewayConfig) -> None: ...
def get_config() -> GatewayConfig: ...   # raises RuntimeError with a clear message if configure() was never called
```

The consuming application calls `abdm_core.config.configure(...)` **once at startup**. `session.py` and `callback_auth.py` read from `get_config()` **at call time**, never at import time.

**This is deliberately narrow.** Only put in `GatewayConfig` what is genuinely shared across every ABDM role. Base URLs that differ by role (`ABHA_BASE_URL`, `HIECM_BASE_URL`, `FACILITY_BASE_URL`, `CALLBACK_URL`) stay out — the calling app owns those and passes them as arguments. If you think something else belongs in here, flag it rather than adding it.

`session.py` keeps the existing `_token_cache` + `_token_cache_lock` design exactly as it is, including the malformed-`expiresIn` guard and the 3-minute refresh margin. Both functions move together because `get_gateway_token()` calls `generate_gateway_token()`; the existing deferred `from server.auth import ...` inside the function body exists only to dodge a circular import and is no longer needed once they share a module — a normal top-level definition order is fine.

## Design decision 2 — storage and log paths must be injected

`flow_logger.py` and `api_capture.py` both locate their output directory with `Path(__file__).resolve().parents[3]`, walking up from inside `repo\` to find the repo root:

```
server/callbacks/utils/flow_logger.py  ->  _LOG_DIR    = parents[3] / "logs"
server/callbacks/utils/api_capture.py  ->  CAPTURE_DIR = parents[3] / "storage" / "api_capture"
```

**This breaks the moment the code lives in an installed package** — `parents[3]` from a site-packages path points at something arbitrary.

Create `abdm_core/paths.py` mirroring the config pattern:

```python
@dataclass(frozen=True)
class StoragePaths:
    log_dir: Path
    storage_root: Path

def configure_paths(paths: StoragePaths) -> None: ...
def get_paths() -> StoragePaths: ...   # clear RuntimeError if unconfigured
```

Then in `flow_logger.py` and `api_capture.py`, replace the module-level `Path(__file__)...` constants with a **lazy lookup at write time**. Directory creation (`mkdir(parents=True, exist_ok=True)`) also moves to write time. Do not resolve paths at import.

**Never delete or truncate anything under an existing `logs/` or `storage/` directory** — not while testing, not to "start clean". Append-only, always.

## Design decision 3 — the certificate cache must be keyed by URL

`server/crypto.py` hardcodes the certificate endpoint:

```python
url = f"{ABHA_BASE_URL}/profile/public/certificate"
```

The PHR app needs a **different** endpoint for the same purpose: `.../phr/app/login/public/certificate`. And eventually both roles may run inside one process, so a single global `_cached_certificate` would let one role serve the other role's certificate — a real, hard-to-diagnose bug.

Change `download_public_certificate()`, `get_public_certificate()`, `refresh_public_certificate()` and `clear_certificate_cache()` to take the **full certificate URL as their first argument**, and change the module-level cache from a single value to a **dict keyed by that URL**, with its TTL tracked per key.

Keep `_cache_lock` and the existing double-checked-locking behaviour — it is there for a real race documented in the file's own comments (tracker case M1-2). One shared lock guarding the whole dict is correct and simpler than per-key locks; don't over-engineer it.

`clear_certificate_cache()` should clear one URL's entry when given a URL, and accept being called with no argument to clear everything (useful in tests).

`encrypt_value(value, public_key)` is pure — it does not change.

## Design decision 4 — `ALLOWED_AZP_VALUES` must become lazy

`jwt_auth.py` currently computes, at import time:

```python
ALLOWED_AZP_VALUES = {"gateway", CLIENT_ID}
```

With configure-at-startup, the import happens before `configure()` runs, so this would either crash or capture a wrong value. Turn it into a function that reads `get_config().client_id` when the check actually runs.

Everything else in that module — the JWKS client, its timeout subclass, the issuer/exp/aud checks, the `asyncio` handling — copies over unchanged. **Do not change any part of the verification logic.** It is security-critical and it is already correct.

## Packaging

Create a `pyproject.toml` using setuptools, package name `aegle-abdm-core`, import package `abdm_core`, `requires-python = ">=3.12"`. Dependencies: `requests`, `cryptography`, `PyJWT`, `fastapi` (needed by `callback_auth.py` for `Request`/`HTTPException`). Pin them consistently with `repo\requirements.txt` — read it, don't guess versions.

Add a short `README.md` stating what the package is, what belongs in it and what deliberately does not, and showing the two-call startup:

```python
from abdm_core.config import configure, GatewayConfig
from abdm_core.paths import configure_paths, StoragePaths
```

Include a `.gitignore` (Python standard: `__pycache__/`, `*.egg-info/`, `.venv/`, `build/`, `dist/`). Do **not** run `git init` or create any commit.

---

## Verification — required, and it needs care

There is **no automated test suite anywhere in this project** (tracker item T-31). So you must build the verification yourself, and it must not touch the network or the real ABDM sandbox.

Write a temporary script that proves all of the following, and show me its actual output:

1. `pip install -e .` into the `aegle-care` conda env succeeds.
2. Every module imports cleanly from a directory that is **not** the package source directory — this is what catches path-anchoring bugs. `cd` somewhere else entirely before importing.
3. Calling `get_config()` or `get_paths()` before configuring raises a clear `RuntimeError`, not an `AttributeError` or `None` dereference.
4. `configure()` + `get_gateway_token()` returns a cached token without a second HTTP call — mock the HTTP layer, assert the request function was called exactly once across two `get_gateway_token()` calls.
5. The malformed-`expiresIn` guard still fires: feed it `None`, `"abc"`, `True`, and `-5` and assert each raises.
6. The certificate cache is genuinely per-URL: mock two different certificate URLs returning two different public keys, fetch both, and assert each URL keeps returning its own key and that each was downloaded exactly once.
7. `flow_logger` and `api_capture` write to the injected directory — point them at a temp dir, write, assert the files land there.
8. Fidelius round-trip: `generate_key_material()` → `encrypt_health_data()` → `decrypt_health_data()` returns the original plaintext. This proves the verbatim copy is intact.

Then **delete the verification script** once it passes. Do not leave it in the repo.

Also run a grep over the finished package for `from server` / `import server` and confirm zero matches — the package must not reference the old repo at all.

---

## Ground rules — these apply to every task in this project

1. **No throwaway scripts left behind.** Delete scratch/verification scripts once they've served their purpose.
2. **Detailed per-file change report at the end** — exactly what changed, where, and why. Plus a short summary I can paste back into my Cowork session for review.
3. **Strict scope discipline.** Change nothing beyond what this prompt specifies. If you spot a bug outside this scope, *flag it, don't fix it*. If you introduce a bug yourself while doing the assigned work, fix that one.
4. **No git commit, no git push, no `git init`.** Make the file changes, verify them locally, leave everything as uncommitted working-tree state. Reviewing and committing is my job.
5. **Never overwrite real output data.** If anything you run could write to or overwrite real data (`logs/`, `storage/`, CSVs, FHIR bundles), back it up first, then restore it exactly afterward. Producing real output is my job, not yours.
6. **Don't claim something works without running it.** "Should work" is not verification.
7. **Flag uncertainty visibly.** If a payload shape, spec detail, or API behaviour is unconfirmed, say so plainly rather than presenting a guess as fact.
