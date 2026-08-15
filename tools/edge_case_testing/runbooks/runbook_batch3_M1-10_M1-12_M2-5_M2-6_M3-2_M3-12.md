# Verification Runbook — Third Batch (6 cases: M1-10, M1-12, M2-5, M2-6, M3-2, M3-12)

Server: `conda activate aegle-care` → `uvicorn server.main:app --reload` (port 8000). Restart before this session for a clean log with the new code.

**Hard rule, unchanged:** never edit, truncate, or delete anything under `storage/` or `logs/`.

This batch is a mix: two are test-tool robustness fixes you'll see directly in the CLI's console output (M1-10, M1-12), two are event-loop-responsiveness fixes you confirm by timing (M2-5, M2-6), one is a real correlation-safety fix (M3-2), and one was already fixed as a side effect of earlier work — confirm only (M3-12).

---

## Set A — M1-10 (empty "tokens" section wrongly reported as a successful login) & M1-12 (non-list accounts field crashes the CLI)

Both fixed in the same function: `tools/m1_test_suite/login_runner.py`'s `verify_login_otp()`.

**Test — M1-10 (needs a faked/proxied response, since ABDM won't hand you an empty tokens section on demand):**

1. Run any login flow that uses the `phr/web/login/abha`-style shape (`{"users": [...], "tokens": {...}}`) — e.g. Flow 6/7 via `python -m tools.m1_test_suite.cli`.
2. Use a proxy tool (mitmproxy, or a quick local stub) to intercept the `verify_otp` response and rewrite `"tokens"` to `{}` (present but empty) before it reaches the CLI.
3. Confirm the CLI now prints `[FAIL] OTP verification returned a 200/success response but no usable token was found...` instead of `[OK] Login succeeded.` — and returns `x_token: None`.
4. Check `tools/m1_test_suite/logs/run_*.log` (read-only) for the `MISSING/EMPTY token` log entry with the full raw response body.

**Test — M1-12:**

1. Same proxy setup; this time rewrite `"accounts"` (or `"users"`) in the verify_otp response to a plain string, e.g. `"no accounts found"`, instead of a list.
2. Run the flow. Confirm the CLI does NOT crash — it should print `[FAIL] OTP verification returned an 'accounts'/'users' field that isn't a list (got str: 'no accounts found')...` and continue gracefully (returns `accounts: []`).
3. Positive control: run one normal login flow with a real, well-formed response. Confirm it still reports success and lists accounts normally.

**Pass criteria:** both malformed shapes are caught and reported clearly, with no crash and no false "Login succeeded."; a normal response still works exactly as before.

---

## Set B — M2-5 (decrypting a data push blocks the whole server) & M2-6 (building FHIR bundles blocks the whole server)

Both fixed by moving the CPU-bound work off the event loop via `asyncio.to_thread()` — same pattern already used everywhere else in this codebase for blocking calls.

**Test — M2-5 (health_information_hiu_push_service.py):**

1. Start the server. In one terminal, trigger a data push with several entries (or several sequential single-entry pushes for a multi-page transfer) so decryption takes a noticeable moment.
2. WHILE that push is being processed, in a second terminal/tab, hit `http://127.0.0.1:8000/health` (or any other lightweight route) repeatedly and time the response.
3. Before this fix, `/health` would visibly stall until decryption finished (single event loop blocked). After the fix, `/health` should respond promptly and independently, regardless of how long the push's decryption takes.

**Test — M2-6 (health_information_request_service.py):**

1. Trigger an M2 Health Information Request flow for a consent with several care contexts / large attachments, so `build_bundles_for_care_contexts()` takes a noticeable moment.
2. Same concurrent-`/health`-check method as above, timed against the bundle-assembly window (visible in the console via the existing `time_block("bundle_assembly", ...)` timing log).
3. Confirm `/health` stays responsive throughout.

**Pass criteria:** the server keeps answering other requests promptly while a decrypt (M2-5) or bundle-assembly (M2-6) is in progress — no visible stall on unrelated requests. This is a responsiveness test, not a correctness test — the push/request itself should still complete and behave exactly as before (same status responses, same data stored).

---

## Set C — M3-2 (overlapping requests crossing encryption keys)

**Fix:** `health_information_hiu_on_request_service.py` now refuses to relink a `transactionId` that's already linked to a different pending `requestId`'s session, instead of silently overwriting the index.

**Test:**

1. Start two Health Information Requests close together (two different `hiu_id`s or just two separate `initiate_health_information_request()` calls) so you have two distinct pending sessions, each with its own `REQUEST-ID` and `key_material`, both unresolved (no on-request callback yet).
2. Find (or capture) a real on-request callback for the FIRST request in `storage/callbacks/` — note its `response.requestId` (request A) and `hiRequest.transactionId` (transaction X).
3. Replay that same on-request callback body, but with the header/REQUEST-ID swapped so `response.requestId` now correlates to the SECOND pending request (request B), while `hiRequest.transactionId` still claims transaction X (the one already linked to request A).
4. Confirm the console logs:
   `transactionId X is already linked to a different pending requestId ('<request A>') -- refusing to relink it to requestId '<request B>'...`
5. Confirm `pending_health_information_requests_by_transaction_id.jsonl` (read-only) still resolves transaction X to request A's session, unchanged.
6. Positive control: let request A's own genuine on-request callback (its real transactionId, its real requestId) go through normally, and confirm the eventual data push for that transaction decrypts correctly with request A's own key material.

**Pass criteria:** the cross-request relink attempt is rejected and logged; the original linkage is untouched; the genuine flow for each request still works independently.

---

## Set D — M3-12 (multi-page push silently overwriting earlier pages) — CONFIRM ONLY, no fix written this batch

This was already fixed as part of the 2026-08-12 multi-page rework (merges pages instead of overwriting) — this batch didn't touch it, just confirming it's real.

**Test:**

1. Trigger a Health Information Request for a consent covering 2+ care contexts, so the HIP side sends multiple pushes (page 0 of N, page 1 of N, ...) for one `transactionId`.
2. After each page arrives, check `storage/hiu_health_information.jsonl` (read-only) for that `transactionId` — confirm the `care_contexts` dict keeps GROWING across pages (each page's entries added, not replacing the previous page's).
3. After the last page, confirm every care context from every page is present in the final merged record, and exactly one `send_health_information_notify` call fired (only after the last page — check the console for a single "Notifying ABDM of Receipt Outcome" line, not one per page).

**Pass criteria:** all pages' care contexts are present in the final stored record; only one notify call for the whole transfer.

---

Send me the console output / results for whichever sets you or your teammate run — passing cases move to Done, failing ones go back to Not started for re-diagnosis.
