# ABDM Integration — Edge Case Test Plan (M1 / M2 / M3)

**v2 — 2026-08-11/12.** Supersedes the v1 pass, which only covered input validation (bad formats, bad-but-plausible values). This pass went much deeper: every M1/M2/M3 source file was read in full (not sampled) specifically hunting for concurrency/race conditions, storage integrity, security/trust-boundary gaps, encryption correctness, timeout/retry behavior, encoding/boundary conditions, malformed-response handling, protocol sequencing bugs, idempotency, and observability — the kinds of things a QA pass focused only on "did I type the field wrong" would never surface. Several items below are **not testable by a human at a keyboard** (they need a proxy, a raw curl request, killing a process, or hand-editing a storage file) — flagged explicitly rather than dropped, per your instruction that "not locally testable" is fine as long as it's real.

**How to use this doc:** run what you can from the CLI as before. For items marked `[not keyboard-testable]`, either skip them for now, or tell me and I'll build a small script/curl command to trigger it and we'll run that together. For every result — pass, fail, or crash — send me the console output plus the matching `storage/api_capture/*.jsonl` entry / `logs/*.log` line and I'll tell you whether it behaved as expected.

**Severity tags:** `[CRITICAL]` data loss, PHI exposure, or auth bypass. `[HIGH]` real functional break, silent wrong behavior, or crash on a realistic path. `[MEDIUM]` degraded/confusing behavior. `[LOW]` cosmetic or very-low-probability. `[AUTHOR-FLAGGED]` the code's own comments already mark this as unconfirmed. `[not keyboard-testable]` needs code/network/storage manipulation, not just typing at a prompt.

---

# START HERE — highest-signal items across all three modules

1. **[CRITICAL]** **M2/M3 callback endpoints have zero authentication.** No signature check, no HMAC, no bearer/IP allowlist on any `/api/v3/hip/*` or `/api/v3/hiu/*` route (`server/callbacks/router.py`, `server/main.py`). Combined with the fact that `dataPushUrl` and `keyMaterial` in a `health_information_request` callback are attacker-controlled fields, anyone who can reach the ngrok URL can make the server build a real patient's FHIR bundle, encrypt it to an attacker-supplied public key, and POST it to an attacker-supplied URL — full PHI exfiltration via two unauthenticated requests. Same hole lets an outsider inject a fake GRANTED consent (`/consent/request/hip/notify`) or a fake fetched-consent artefact (`/hiu/consent/on-fetch`, which has **no correlation check at all**). See M2 §D1/D2, M3 §E1/C5.
2. **[CRITICAL]** **AES-GCM key+nonce reuse across every care context in one M2 data push.** `generate_key_material()` is called once per transfer, then reused for every bundle in the loop — same key, same IV, every time a consent covers ≥2 care contexts. This is a textbook nonce-reuse break: XOR of two ciphertexts leaks structure, and the GCM auth key becomes recoverable. See M2 §D5.
3. **[HIGH]** **Duplicate/replayed ABDM callbacks aren't deduped anywhere**, and the server never fast-acks (it fully processes before returning 200, so a slow chain invites ABDM's own retry). A replayed `consent_notify` can **resurrect a revoked consent** (GRANTED → REVOKED → replayed-GRANTED = usable again); a replayed `health_information_request` re-pushes the same PHI under a second encryption key and sends ABDM two conflicting "transfer complete" notifications. See M2 §B0/B1/B2.
4. **[HIGH]** A **failed M1 enrollment can be silently presented as a benign, normal state.** `enroll_by_aadhaar()` has no check for ABDM's documented 200-but-actually-failed shape (unlike every login flow, which does). On that shape, the code's own fallback message — "Mobile number was not verified during enrollment" — describes something completely different from "enrollment failed," and reads as normal. This is the single most dangerous "looks fine, isn't" case in the whole plan. See M1 §C-12.
5. **[HIGH]** **Copy-pasted OTPs with invisible characters silently burn all 3 retry attempts.** `str.strip()` does not remove zero-width spaces or bidi marks — verified empirically. An OTP copied from a formatted SMS/WhatsApp/email can look 100% correct on screen and fail three times with no way for the user to tell why. See M1 §E-4.
6. **[HIGH]** **Every M2/M3 callback handler swallows its own exceptions and still tells ABDM "OK."** Every service's top-level `except Exception: log_error(...); return` combined with the router always returning `{"status":"OK"}` 200 means a malformed-payload crash is **invisible to ABDM, invisible to the HIP/HIU on the other end, and invisible to you** unless someone greps the log file. This one pattern is the reason so many of the "malformed payload" findings below matter more than they'd otherwise seem to.
7. **[HIGH]** **M3's outbound/inbound key-material format is asymmetric and will break real interop.** M3 *sends* its own public key raw, but *requires* X.509-DER on the way in with no fallback. A real third-party HIP that mirrors our own outbound convention (raw) will have every single data push rejected as "could not decode HIP's public key." See M3 §H2.
8. **[CRITICAL, compliance]** **`permission.dataEraseAt` from the consent artefact is stored and never enforced.** Received PHI sits in `storage/hiu_health_information.jsonl` forever with no purge job — this isn't just a QA nit, it's a real gap against the consent's own stated data-retention terms. See M3 §C2.
9. **[MEDIUM but very likely to recur]** **`patients.csv` full_name vs. Aadhaar-on-record name mismatches (the ABDM-1207 bug we already hit for PAT9002) can recur for any other test patient** — worth a one-time audit of all rows, not just the one that broke.

Everything below is the full backing detail, organized by module.

---

# M1 — ABHA Enrollment / Login

*M1 touches no shared storage layer — its only durable records are `storage/api_capture/m1_*.jsonl` and `tools/m1_test_suite/logs/run_*.log`. That has its own consequences (§G below).*

## A. Module-level caches / concurrency

1. **Test Case:** `[not keyboard-testable]` `server/crypto.py`'s `_cached_certificate` global is never refreshed anywhere in the codebase — `refresh_public_certificate()`/`clear_certificate_cache()` exist but have zero call sites. Simulate an ABDM certificate rotation by patching `_cached_certificate` to a different (but still valid) RSA key mid-session, then run a login flow.
   **Expected:** A detectable cert-mismatch error. **Suspected:** Local encryption succeeds silently (any valid RSA key encrypts fine locally), ABDM fails to decrypt, and the user sees a generic Aadhaar/OTP-looking 400 with zero indication the *certificate* is stale. A long-running server process would stay broken until manually restarted. **[HIGH]**

2. **Test Case:** `[not keyboard-testable]` Fire two concurrent server-side ABDM callbacks on a cold certificate cache (`server/crypto.py:124-132`'s check-then-act race, no lock).
   **Expected:** One download. **Suspected:** N concurrent downloads — wasted work and log noise, not a correctness bug (final assignment is atomic in CPython). **[LOW]**

3. **Test Case:** `[not keyboard-testable]` `server/utils.py`'s `_token_cache` (gateway bearer token) is a plain unguarded dict now accessed from many `asyncio.to_thread` worker threads (M2/M3 both call through it). Fire two concurrent callbacks right as the cached token crosses its 3-minute refresh window.
   **Expected:** One refresh. **Suspected:** Both threads refresh; the loser's token silently overwrites the winner's in the shared cache. Benign most of the time, but if ABDM ever invalidates the prior session on new-session issue, the *surviving* cached token could be the dead one — sporadic, non-reproducible 401s. **[MEDIUM]**

4. **Test Case:** After a successful login, manually corrupt the cached token in-process (`server.utils._token_cache["access_token"] = "garbage"`, needs a debugger/REPL) and run another flow. `[not keyboard-testable]`
   **Expected:** Auth failure detected, one re-mint attempted before surfacing an error. **Suspected:** There is no 401-triggered cache invalidation anywhere — every call fails with a raw 401 for the rest of the token's nominal lifetime, and the console message ("OTP request failed, status 401") will point the tester at the OTP, not the token. **[HIGH]**

## B. Gateway-token failure misclassification

5. **Test Case:** `[not keyboard-testable, needs a proxy]` Point the gateway token endpoint at something returning `200 text/html` (a gateway/proxy error page). Verified: `requests.exceptions.JSONDecodeError` subclasses **both** `RequestException` and `ValueError` in this project's `requests` version, and `server/utils.py`'s `except RequestException` is listed *before* `except (KeyError, ValueError)` — so the malformed-JSON branch the author actually wrote is dead code for this exact case.
   **Expected:** "Gateway token response was malformed." **Suspected:** "Gateway token request failed" (misreported as connectivity, not a bad response body). **[MEDIUM]**

6. **Test Case:** `[not keyboard-testable]` Stub `expiresIn` as a string (`"1800"`) or `null` in the token response. `timedelta(seconds=...)` raises `TypeError`, caught by neither of the two except clauses present.
   **Expected:** Same malformed-response message. **Suspected:** Raw `TypeError` reaches the CLI's generic handler with no indication it came from the token endpoint. **[MEDIUM]**

## C. Malformed / unexpected ABDM response shapes

*This is the largest cluster in M1: every flow module calls `response.json()` on the success path with no guard, even though `server/abha.py`'s own `_post()` defends against non-JSON — that defensiveness is only used for the audit-capture write, never handed back to the caller.*

7. **Test Case:** `[not keyboard-testable, needs a proxy]` Interpose a proxy that rewrites any single ABDM 200 body to HTML (a classic gateway/CDN interstitial) during Flow 1/2/3/etc.
   **Expected:** "ABDM returned an unreadable response," clean return to menu. **Suspected:** Raw `JSONDecodeError` at the CLI's generic exception handler — the *actual* body is captured to `storage/api_capture/m1_*.jsonl` but nothing on screen tells the user to look there. **[MEDIUM]**

8. **Test Case:** `[not keyboard-testable]` Same as #7 but specifically against the public-certificate endpoint (`server/crypto.py:86` re-parses the response a **second** time, fully unguarded, right after the function's own defensive parse four lines earlier had already handled the non-JSON case once).
   **Expected:** Clean "certificate missing publicKey" error. **Suspected:** Crash at the very first prompt of *every* flow, since every flow calls `encrypt()` first. **[MEDIUM]**

9. **Test Case:** `[not keyboard-testable]` Stub the certificate response as `{"publicKey": {"pem": "..."}}` (a non-string publicKey passes the existing truthiness check, then dies on `.strip()`).
   **Expected:** Clean validation error. **Suspected:** Raw `AttributeError`. **[LOW]**

10. **Test Case:** `[not keyboard-testable]` Force `{"tokens": null}` on the phr/web/login/abha response shape (Flow 6/7). `.get("tokens", {})` does **not** protect against an explicit `null` (defaults only apply to *absent* keys) — `None.get("token")` then raises.
    **Expected:** Handled the same way the adjacent `accounts` field already is (that one correctly uses `or []`, this one doesn't). **Suspected:** `AttributeError` *after* a real OTP has already been consumed — the user loses a live OTP to a code path bug, not their own mistake. **[HIGH]**

11. **Test Case:** `[not keyboard-testable]` Force ABDM's search response (Flow 8, `login_search.py`) to be an object instead of an array — `body[0]` bracket-indexes with no type guard, only an emptiness guard.
    **Expected:** Graceful "unexpected response shape." **Suspected:** Raw `KeyError: 0`. Worth noting the two "search ABHA" flows in this codebase (Flow 8 vs. Flow 13) assume *opposite* container types (list vs. dict) for what may or may not be genuinely different endpoints — worth confirming both are actually correct, not just consistent with each other. **[MEDIUM] [AUTHOR-FLAGGED]**

12. **Test Case:** `[not keyboard-testable]` Force `accounts: ["91-1234-...']` (bare strings instead of account objects) on any login flow's verify step.
    **Expected:** Graceful degradation. **Suspected:** `AttributeError` inside the account-printing helper, occurring **after** "Login succeeded" has already been printed — the user sees a success message immediately followed by a traceback, and the session's X-Token is discarded even though login genuinely worked. **[HIGH]**

13. **Test Case:** Set `MAX_OTP_ATTEMPTS = 0` (code-level, not keyboard) and run Flow 3. Every path inside the retry loop currently returns something, so the implicit `None` fall-through is unreachable *today only because the constant is > 0* — a real bug lying dormant behind a config knob. `[not keyboard-testable]`
    **Expected:** N/A / not a real scenario today. **Suspected:** `TypeError: 'NoneType' object is not subscriptable` if that constant is ever tuned down. **[LOW, regression-guard]**

14. **Test Case:** `[not keyboard-testable]` Strip `token` from the `verify/user` 200 response (Flow 3's account-selection step).
    **Expected:** "Login did not return a token." **Suspected:** Console prints "Login complete for the selected account." and `X-Token: None` in the same breath — a flat contradiction a tester would have to notice themselves. **[MEDIUM]**

15. **Test Case:** `[not keyboard-testable]` Strip `txnId` from the OTP-request response during Flow 1 (Enrollment).
    **Expected:** Caught before prompting for an OTP that can never succeed. **Suspected:** User is prompted for an OTP anyway; `txnId: null` is sent straight into the enrollment call, producing an opaque rejection with no hint the transaction ID was ever missing. **[MEDIUM]**

16. **Test Case:** Enter a deliberately wrong OTP at **Flow 1 (Enrollment)** specifically (not a login flow). This is the concrete way to trigger START-HERE item #4 (`enroll_by_aadhaar()` has no `authResult` check, unlike every login flow — the code's own comment flags this as an open, unresolved question).
    **Expected:** A clear "wrong OTP" failure, same as the login flows get. **Suspected:** If ABDM uses its documented 200-but-failed shape here too, the enrollment is silently reported via the "mobile not verified" message — describing a totally different, benign outcome. **[HIGH] [AUTHOR-FLAGGED]** — highest priority item to actually run in this whole module.

17. **Test Case:** Run Flow 13 (Search ABHA by Address) against a **known-good, existing** ABHA Address, and diff the printed "not found" heuristic outcome against the raw logged response body.
    **Expected:** Reported as found. **Suspected/unconfirmed:** The code's own docstring flags this heuristic (treats "200 with no recognizable ABHA-number-shaped key" as not-found) as never live-confirmed — a genuinely found account could be misreported as missing if the real response uses a field name outside the three guessed. **[MEDIUM] [AUTHOR-FLAGGED]**

18. **Test Case:** Run Flow 7 end-to-end and diff its logged response shape against Flow 6's (the code assumes, but has never separately confirmed live, that they match). **[AUTHOR-FLAGGED, low effort to just run]**

19. **Test Case:** Run Flow 8 (Search) with the `index` value sent **unencrypted** vs. the current encrypted implementation, and compare outcomes — the encryption of this particular field is a documented guess, not a confirmed detail. **[AUTHOR-FLAGGED]**

20. **Test Case:** Complete a real Flow 1 enrollment and diff the console's printed "ABHA Number" against the raw logged body — the JSON key used for it is a guess between two plausible names; if both miss, a fully successful enrollment prints `ABHA Number : None`. **[MEDIUM] [AUTHOR-FLAGGED]**

## D. Network timeouts, retries, partial failures

21. **Test Case:** `[not keyboard-testable, needs to blackhole a host]` Disable network to `abhasbx.abdm.gov.in` right after typing an OTP but before submitting it.
    **Expected:** A retry, or at least a message about whether server-side state might have changed. **Suspected:** Generic connection-error message with **zero statement about server-side state** — did the enrollment go through or not? **[MEDIUM]**

22. **Test Case:** `[not keyboard-testable, needs a proxy]` Use a proxy that accepts an `enrol/byAadhaar` request, forwards it, but withholds the response past the 30s client timeout, while ABDM actually eventually succeeds server-side.
    **Expected:** "The request may have gone through — verify before retrying." **Suspected:** Generic timeout error → tester naturally re-runs the same enrollment → ABDM returns the *already-existing* account → code prints "ABHA already existed... this is a normal success, not an error" — which is technically true but **masks that the first, timed-out attempt is the one that actually created it.** The only evidence is buried in the api_capture file. **[HIGH]**

23. **Test Case:** `[not keyboard-testable]` `server/auth.py`'s `update_bridge_url()` is the **one** outbound call in the entire codebase with **no `timeout` parameter at all** — every sibling call has `timeout=30`. Point it at a host that accepts the TCP connection and never responds.
    **Expected:** Fails after ~30s like everything else. **Suspected:** Hangs the process indefinitely, un-killable except by Ctrl-C. One-line fix once confirmed. **[MEDIUM]**

24. **Test Case:** `[not keyboard-testable]` The ABHA card/QR download calls stream binary content with a per-chunk (not total-call) 30s timeout. Serve the response through a proxy trickling one byte every ~25 seconds.
    **Expected:** Times out within a bounded window. **Suspected:** Never times out as long as *some* byte arrives every <30s — the call can hang indefinitely on a slow-loris-style response. **[LOW, needs proxy]**

## E. Encoding, encryption, and boundary conditions

25. **Test Case:** Paste 500+ characters into any encrypted field (Aadhaar, mobile, OTP, ABHA Address, email). **Verified empirically:** ABDM's real sandbox key is 4096-bit RSA; OAEP-SHA1's max plaintext for that key size is exactly **470 bytes** — 470 encrypts fine, 471 throws.
    **Expected:** A clean "input too long" message before any crypto is attempted. **Suspected:** Raw `ValueError: Encryption failed` at the generic exception handler, with no mention of length at all. **[MEDIUM, easily keyboard-testable — just paste a long paragraph]**

26. **Test Case:** Paste ~120 emoji into the Aadhaar prompt, then ~200. Unicode shrinks the effective character budget (emoji = 4 UTF-8 bytes each) well below what "looks like" a short string.
    **Expected:** Consistent handling regardless of script. **Suspected:** The 120-emoji case silently encrypts and gets sent to ABDM as garbage in an Aadhaar field; the 200-emoji case throws the opaque error from #25 — two different failure modes for the same underlying mistake. **[LOW-MEDIUM]**

27. **Test Case:** At the main menu, type a superscript/non-decimal digit character (e.g. a copy-pasted `²`), then separately try an Arabic-Indic numeral. **Verified empirically:** `"²".isdigit()` is `True` but `int("²")` raises; `"١".isdigit()` is `True` **and** `int("١") == 1`.
    **Expected:** "Invalid choice" message. **Suspected:** The superscript case is an **uncaught crash that kills the whole CLI** (this check sits outside the try block that wraps flow handlers); the Arabic-Indic case silently launches Flow 1 without the user typing an ASCII "1". **[HIGH — trivially keyboard-testable, and a full CLI crash from one stray character is bad UX at minimum]**

28. **Test Case:** Copy an OTP from a real SMS/WhatsApp/email (which often carry invisible formatting characters) and paste it directly rather than retyping it. **Verified empirically:** `str.strip()` does not remove zero-width spaces or bidi marks.
    **Expected:** Works exactly like a manually-typed OTP. **Suspected:** An invisible character rides along, gets encrypted with the OTP, gets rejected by ABDM, and the user watches a visually-correct OTP fail all 3 retry attempts with zero way to diagnose why. **[HIGH — this is realistic, common user behavior, not an edge case in the "unlikely" sense]**

29. **Test Case:** Type an Aadhaar number with the spacing it's actually printed with on the physical card (`1234 5678 9012`) at a prompt whose own label says "no spaces/dashes."
    **Expected:** Either accepted (auto-stripped) or clearly rejected. **Suspected:** Sent to ABDM with embedded spaces intact, generic rejection — the prompt already states the rule but nothing enforces it. **[LOW-MEDIUM, easily keyboard-testable]**

30. **Test Case:** `[not keyboard-testable without piped stdin]` Send a literal null byte into the ABHA Address field (Flow 11 — the **one** identifier sent unencrypted and completely unvalidated straight into the request body, with no length bound either).
    **Expected:** Local rejection. **Suspected:** Unknown ABDM behavior; also means a 10,000-character ABHA Address (or one containing `../`, `<script>`, a newline) gets written verbatim into the audit-capture file with no bound. **[LOW-MEDIUM]**

## F. CLI control flow, EOF, interrupts

31. **Test Case:** Press Ctrl-D at the main "Select a flow" prompt (or `python cli.py < /dev/null`). **Easily keyboard-testable.**
    **Expected:** Clean exit, same as typing 0. **Suspected:** Uncaught `EOFError` — worse, **any flow that later hits EOF on stdin also raises EOFError, gets caught generically, returns to the menu, and immediately re-hits EOF again**, meaning any piped/scripted input to this CLI always ends in a traceback. This makes the tool impossible to drive from an automated script, which matters if you ever want to regression-test these flows non-interactively. **[MEDIUM-HIGH]**

32. **Test Case:** Start Flow 1, receive a real OTP, then Ctrl-C at the OTP prompt instead of entering it.
    **Expected:** A note that a live OTP/transaction was just abandoned. **Suspected:** Generic "cancelled" message with no such warning; re-entering the flow requests a brand-new OTP with no attempt to check whether ABDM rate-limits repeated OTP requests against the same Aadhaar (worth testing directly: request 5 OTPs in a row for one Aadhaar). **[MEDIUM]**

33. **Test Case:** At any account-selection prompt with 2+ results, try to back out without picking one.
    **Expected:** A "cancel" option. **Suspected:** No escape exists except Ctrl-C/Ctrl-D — and if there's exactly **one** result, the CLI auto-selects it with no chance to decline at all. **[LOW]**

## G. State, sequencing, resumability

34. **Test Case:** Run Flow 1 to completion, `kill -9` the CLI process right before the final summary prints, then try to determine — using only this tool, no ABDM portal — whether the ABHA was actually created.
    **Expected:** Some recoverable trace. **Suspected:** M1 has **zero persistence of any kind** — every `txn_id`/token lives only in a local variable. The one durable trace (`storage/api_capture/m1_*.jsonl`) is explicitly marked in its own docstring as **"temporary... meant to be removed"** — meaning M1 is on a path to becoming fully unauditable. Flagging this as an architectural question for you, not just a test case. **[HIGH, architectural]**

35. **Test Case:** `cd` to a directory other than the repo root, then launch the M1 CLI from there and run any flow.
    **Expected:** Capture lands in the repo's `storage/api_capture/`. **Suspected:** The capture path is resolved **relative to the current working directory**, not the repo root (unlike this same codebase's own `flow_logger.py`, which does it correctly) — a stray `storage/` tree gets created wherever the CLI happened to be launched from, silently splitting the one audit trail M1 has. **[MEDIUM]**

36. **Test Case:** Run Flow 11 (Create ABHA Address) and force the chained enrollment step to fail *after* its OTP request succeeds (e.g. deliberately wrong OTP, assuming ABDM's rejection is a non-200).
    **Expected:** "Enrollment did not complete — nothing to create an address for," matching Flow 10's identical guard. **Suspected:** Flow 11's guard only checks that `txn_id` is truthy, not that the enrollment `response` is non-null — and a failed enrollment returns exactly that combination (truthy leftover txn_id, null response). Flow 10, built to the same pattern, checks both. **This is a concrete, provable inconsistency between two sibling flows, not a hypothetical.** **[HIGH — easily keyboard-testable]**

37. **Test Case:** Run Flow 10 (Link Mobile) through each of its 5 different exit points and compare the `txn_id` shown in the end-of-run summary each time.
    **Expected:** Consistent meaning. **Suspected:** The same `"txn_id"` return-dict key holds the *enrollment* transaction on some exit paths and a *brand-new OTP* transaction on others — nothing downstream depends on this today, but the CLI's own docs describe the return dict as something later flows might chain off of. **[LOW today, worth knowing]**

38. **Test Case:** `[not keyboard-testable]` Strip `txnId`/`index` from the Search response (Flow 8/9).
    **Expected:** A clear "response missing transaction ID" message. **Suspected:** The flow just... ends, printing nothing at all — the only clue is the raw returned dict the CLI prints afterward. **[MEDIUM]**

## H. Idempotency / double-submit

39. **Test Case:** Two terminals, same Aadhaar, both sitting at the OTP-verify prompt with the same correct OTP — submit both within the same second. **Easily keyboard-testable with two windows.**
    **Expected:** One succeeds, one gets a clear "already used" message. **Suspected:** Unknown at the ABDM level, but locally: the *losing* process either gets a generic failure or (if ABDM returns its 200-but-failed shape) gets told its **correct** OTP is wrong and burns 2 more retry attempts on an OTP that already succeeded elsewhere. **[MEDIUM-HIGH]**

40. **Test Case:** Enter a wrong OTP once, then the genuinely correct one on attempt 2.
    **Expected:** Attempt 2 succeeds. **Suspected/unconfirmed:** The retry loop resubmits against the *same* transaction ID every time — if ABDM invalidates a transaction on its first failed attempt (common in real OTP systems, never confirmed either way here), attempts 2 and 3 would fail identically regardless of correctness, actively training the user to distrust a correct OTP. **[HIGH, worth confirming directly — this affects whether the existing 3-attempt retry feature is even net-positive]**

41. **Test Case:** At Flow 11's "Make this the preferred ABHA Address? (Y/n)" prompt, answer literally `0`.
    **Expected:** Treated as "no" (0 = false is the obvious reading). **Suspected:** The code only checks for `"n"`/`"no"` — anything else, including `"0"`, resolves to **preferred = 1 = yes**. The console then prints `(preferred=1)` in the same breath as "Creating..." with no chance to notice the flip before it's sent. This silently makes an address preferred on a **real ABHA account** against the user's explicit answer. **[HIGH — trivially keyboard-testable, real-account consequence]**

42. **Test Case:** Trigger two downloads (ABHA Card / QR Code) within the same second.
    **Expected:** Either a distinct filename or a warning. **Suspected:** Filenames are only second-granularity — the second overwrites the first silently, both reported as "saved successfully." The same second-granularity issue affects the CLI's own run-log filename: two CLI processes started in the same second interleave their log entries with no process marker. **[LOW]**

## I. Binary / content-type handling

43. **Test Case:** Run "Download ABHA Card" for an account state where ABDM would actually return a JSON error body at 200 (or intercept and force this).
    **Expected:** "Card not available" message. **Suspected:** The JSON error body gets written to disk as a `.bin` file and reported as a successful download — there's no check on content length, magic bytes, or whether the Content-Type is even one of the three the code knows how to map. `[partially keyboard-testable depending on account state]` **[MEDIUM]**

## J. Sensitive-data exposure — worth your explicit attention, not just "testing"

44. **Test Case:** Complete a real Flow 1 enrollment and read the final "Returned: ..." summary line the CLI prints.
    **Expected:** A short, redacted summary (the codebase elsewhere is deliberate about this — e.g. an explicit comment on the profile-utilities download path says "NOT dumped to console, could include a base64 photo"). **Suspected:** The CLI's redaction helper only strips a top-level `x_token` key — the **full enrollment response body** (name, DOB, gender, address, ABHA number, possibly more) is printed in full, undoing that same codebase's own stated intent 60 lines away. **[HIGH — real PII on screen/scrollback/screen-share, easily keyboard-testable, just read the output of any successful enrollment]**

45. **Test Case:** Complete any login flow and read the final summary line.
    **Expected:** Same redaction as the in-flow account list already applies. **Suspected:** The full, unredacted `accounts` list (name, ABHA number, ABHA address per account) prints again in the summary, right after the flow's own deliberately-abbreviated account list already printed a cleaner version. **[MEDIUM]**

46. **Test Case:** `grep -o '"Authorization": "Bearer [^"]\{0,30\}' storage/api_capture/m1_*.jsonl` after running any flow.
    **Expected/note:** These files are already `.gitignore`'d (not a *commit* risk), but they are a plaintext, unredacted, un-rotated local-disk-at-rest record of every bearer token, X-Token, and (for enrollment specifically) the plaintext mobile number this session ever used. Worth an explicit decision on whether that's an accepted risk or something to redact. **[MEDIUM, policy question more than a bug]**

47. **Test Case:** `git log -p -- server/config.py | grep CLIENT_SECRET`.
    **Expected:** No secret in history, or an accepted-sandbox-only exception. **Suspected/confirmed:** `CLIENT_ID`/`CLIENT_SECRET` are hardcoded directly in `server/config.py`, which is tracked in git with a GitHub remote — the sandbox credentials are in history permanently regardless of any future rotation of the value itself. Flagging prominently because M1 is the module marked "complete," i.e. the one most likely to get copied forward into something more permanent as-is. **[CRITICAL if this repo or its history ever becomes non-private / production-adjacent]**

## K. Logging / observability gaps

48. **Test Case:** Trigger any error (e.g. #25's oversized-input case) and note that `log_error()` writes at **INFO level** to the same console handler as normal narration — there is no way to raise the console's visibility for real errors without also silencing everything else, since every log line is emitted at the same level. **[MEDIUM, cross-cutting — affects every "confirm the error surfaced cleanly" test case in this whole document]**

49. **Test Case:** Set your system clock ~90 seconds fast and run any login flow. This codebase has an explicit `generate_safe_past_timestamp()` helper built specifically because "ABDM's validation appears to reject a timestamp that looks even slightly in the future" — but **no M1 call site uses it**; M1 always uses the plain current-time helper.
    **Expected:** Works regardless of minor clock skew. **Suspected:** Intermittent, machine-specific rejections tied to clock drift, with no error message that would ever point a tester at "check your system clock." **[MEDIUM — genuinely worth running once]**

---

# M2 — HIP-Initiated Linking / Consent (Data Sharing)

## A. Concurrency / storage-layer race conditions

*Every M2 callback is processed on an asyncio event loop, with blocking calls offloaded to worker threads via `asyncio.to_thread()`. The state store underneath (`server/callbacks/utils/json_file_store.py`) is a plain-append JSONL file with, by the module's own docstring, no locking — "rare interleaving" is an accepted, documented risk, which is exactly why it belongs in this test plan rather than being assumed away.*

1. **Test Case:** `[not keyboard-testable]` Fire two callbacks concurrently that both write large records to the same storage file — e.g. two `curl` POSTs to `/api/v3/consent/request/hip/notify` in parallel, each with an artificially large `consentDetail.careContexts` array — then read the file back.
   **Expected:** Both records intact. **Suspected:** Interleaved partial writes on records larger than a single OS write buffer; a corrupted line is silently dropped on the next read with **no error logged anywhere** — a granted consent or pending session can vanish with zero trace. **[HIGH]**

2. **Test Case:** `[not keyboard-testable]` Race a `delete_pending_link_token()` call against a concurrent `save_pending_link_token()` for the same key — the delete path is a non-atomic read-then-append.
   **Expected:** Deterministic outcome either way. **Suspected:** A `set` landing between the delete's internal read and its write gets immediately tombstoned — a lost write on exactly the code path that was supposedly hardened against lost writes. **[MEDIUM]**

3. **Test Case:** `[not keyboard-testable, needs a scripted load]` Grow `consents.jsonl` to a large size (script tens of thousands of append/delete cycles), then time a single lookup during a live callback.
   **Expected:** Sub-millisecond. **Suspected:** Every lookup is a full-file scan + JSON-parse of every line, run **directly on the event loop** (not offloaded) at several call sites — meaning storage growth degrades every other in-flight ABDM callback's response time, not just the slow one. No compaction exists anywhere in the codebase; tombstoned/deleted rows are never purged. **[HIGH under real, sustained usage]**

4. **Test Case:** `[not keyboard-testable]` Several concurrent worker threads (e.g. a multi-artefact consent grant, or discover+consent_notify+data-push landing close together) all call the gateway-token helper right as the cached token nears expiry.
   **Expected:** One refresh. **Suspected:** N concurrent refreshes, last-writer-wins, same class of risk as M1 §A3. **[MEDIUM]**

5. **Test Case:** `[not keyboard-testable]` M2's own Fidelius (Curve25519) scalar multiplication is pure-Python and runs directly inside an `async def` handler for the **decrypt** path (M3's push handler specifically) — not wrapped in `asyncio.to_thread` the way every other blocking call in this codebase is, despite the codebase's own convention comment claiming "every blocking call is wrapped this way."
   **Expected:** Other callbacks keep being served promptly during a decrypt. **Suspected:** The event loop is pinned for the full scalar-mult duration per entry — for a multi-entry push this can add up to a meaningful stall, during which ABDM callbacks arriving get delayed acks and may be retried by ABDM (feeding directly into the duplicate-callback section below). **[HIGH]**

6. **Test Case:** `[not keyboard-testable]` Trigger a `health_information_request` for a consent covering many care contexts, each with a large attachment — the FHIR-bundle-assembly step (CSV loads + attachment base64-encoding) runs directly on the event loop, only the *encryption/push* step afterward is offloaded.
   **Expected:** Assembly offloaded like everything else, per the codebase's own stated convention. **Suspected:** The loop stalls for the full assembly duration — this is a second instance of the same class of bug as #5, on a different code path. **[HIGH]**

7. **Test Case:** Trigger the documented ABDM-1006 "no links found" retry path (run Notify Care Context Update immediately after Link Token Generation, faster than ABDM's own propagation — already listed as a functional test in v1, repeated here for a structural reason): the retry call itself is a **synchronous, un-offloaded** `requests.post` after a 5-second sleep, up to ~35 seconds total directly on the event loop.
   **Expected:** Offloaded like the rest of the retry-adjacent code. **Suspected:** This is the *same class* of self-blocking bug the already-documented "event loop deadlock" fix addressed elsewhere, but this specific path wasn't caught by that fix — likely because it's timing-race-triggered and hard to hit in casual testing (which is exactly why it's worth deliberately forcing here). **[HIGH]**

8. **Test Case:** `[not keyboard-testable]` Flip the M3 trigger mode from `"manual"` to `"auto"` (`server/config.py`) and run a multi-HIP consent grant. In this mode, the on-fetch → auto-trigger-health-information-request → our-own-push-endpoint chain re-opens the same category of self-referential-call risk the original deadlock fix addressed, on a code path that (per the config default) has likely never actually run yet.
   **Expected:** No deadlock/stall. **Suspected:** Unverified — worth a deliberate one-time test specifically because this mode is dormant and therefore untested. **[MEDIUM, but genuinely unknown]**

## B. Duplicate / replayed ABDM callbacks

*Root cause worth understanding before the individual cases: every callback route fully awaits its handler (which can involve several outbound 30-second-timeout calls) before returning the ack — the server never fast-acks-then-processes-async the way ABDM's own protocol design assumes. If ABDM's own retry timeout is shorter than our total processing time, ABDM will retry, and every case below is what happens when it does. Also note: routes always return HTTP 200, never 202, even where the pattern elsewhere is 202.*

9. **Test Case:** `[not keyboard-testable, raw curl needed]` POST the same GRANTED `consent_notify` body twice, with a REVOKED notify for the same consentId POSTed in between.
    **Expected:** The consent stays revoked. **Suspected:** There's no timestamp/version/ordering check on notifications at all — the second (replayed) GRANTED silently **resurrects a revoked consent**, making it usable again for a later health-information request. **[CRITICAL — this is the single highest-severity duplicate-callback finding, both because it's plausible under real ABDM retry behavior and because the consequence is a genuine consent-bypass]**

10. **Test Case:** `[not keyboard-testable]` Replay a captured `health_information_request` body (there are real ones sitting in `storage/api_capture/m2_*.jsonl` already) via curl.
    **Expected:** Idempotent no-op, or a clear duplicate-detected rejection. **Suspected:** No "have I already processed this transactionId" check exists — the full record-build, a **fresh** encryption key, a second push to the HIU, and a second (conflicting) "transfer complete" notification to ABDM all happen again. The HIU receives the same PHI twice under two different keys; ABDM gets told the same transfer completed twice. **[HIGH]**

11. **Test Case:** `[not keyboard-testable]` Send two `generate_token` (on-generate-token) callbacks for the same request within a ~1-second window.
    **Expected:** Second one is a no-op. **Suspected:** The "delete this pending request" step only happens *after* the full linking chain completes — within that window, both callbacks find the pending record still present and both trigger the full link + notify chain, producing duplicate `pending_care_context_links` and a doubled Notify chain per care context. **[MEDIUM-HIGH]**

12. **Test Case:** `[not keyboard-testable]` Same idea for `care_context_link` (on_carecontext) — the pending record is deleted only after the *entire* per-care-context notify loop completes, not before it starts.
    **Expected:** One notify chain per care context regardless of replay timing. **Suspected:** A replay while the first is still looping produces roughly double the notify calls, some of which may hit the ABDM-1006 timing race and each spin up their own 5-second-sleep retry (item A7 above) — a plausible cascade under real-world retry conditions. **[MEDIUM]**

13. **Test Case:** `[not keyboard-testable]` `link_init` (User-Initiated Linking) has **no dedupe at all** — a duplicated `care-context/init` callback requests a **second, brand-new OTP** from ABDM and saves a second link session under a second reference number.
    **Expected:** One OTP, one session. **Suspected:** The patient gets two OTP SMS messages for what looks like one link attempt; only one of the two sessions will ever be confirmable, and the other lingers as orphaned state (ties into the storage-growth section below). **[MEDIUM]**

## C. Storage integrity, tombstones, unbounded growth

14. **Test Case:** `[not keyboard-testable]` `kill -9` the server process mid-write during a large `save_consent()` call, restart, then write a *new*, unrelated consent and try to read it back.
    **Expected:** At worst, lose the one truncated record. **Suspected:** A partial last line (no trailing newline) causes the *next* successfully-written record to get concatenated onto the garbage and fail to parse too — silently losing **two** records for the price of one crash, with no log line calling this out. **[HIGH — direct PHI/consent-state loss]**

15. **Test Case:** Inspect `storage/pending_care_context_notifies.jsonl` and `storage/pending_link_tokens.jsonl` directly — they already show roughly 50% tombstone-to-live-row ratios from normal testing so far.
    **Expected:** Some compaction over time. **Suspected:** There is no compaction mechanism anywhere in the codebase — every one of these files grows monotonically forever, and every lookup against them is a full-file re-scan (see §A3). At real production volume this is a genuine, if slow-building, reliability problem, not just disk usage. **[MEDIUM, long-horizon]**

16. **Test Case:** `[not keyboard-testable]` Hand-edit `storage/consents.jsonl` to give one row a `"value"` that's a plain string instead of the expected object, then trigger a health-information request against that consentId.
    **Expected:** A clear "corrupted consent record" error. **Suspected:** `AttributeError` deep inside the health-information-request handler, caught generically — no ack sent, no failure notify sent to ABDM either (ties into §B6, the "swallowed failure looks like OK to ABDM" pattern). **[MEDIUM, but a good test of the broader error-swallowing pattern]**

17. **Test Case:** Check whether `health_information_repository`'s in-memory session dict (which holds full decrypted FHIR bundles, base64 attachments included, per active transaction) is ever actually evicted after a transfer completes — there's a delete function defined but grep shows **zero call sites** for it anywhere in the codebase.
    **Expected:** Freed promptly after each transfer. **Suspected:** Unbounded growth of decrypted PHI held in server RAM for the life of the process — under sustained real usage with large attachments this is both a memory-pressure risk and, notably, data that's lost (not "safely cleared") on restart, meaning a legitimate later lookup for that transaction also silently fails. **[HIGH, worth a direct memory check after running several data-push flows in a row]**

18. **Test Case:** Confirm which storage files are actually authoritative. Several old pre-JSONL `.json` files (`pending_link_tokens.json`, `patient_link_tokens.json`, etc.) still exist alongside their `.jsonl` replacements and, per a repo-wide check, are never read by current code — but they'd silently become "live" again if any older code path or rollback ever re-imported them. **[LOW, but worth a one-time cleanup/confirmation]**

## D. Security (independent of any input-validation gap)

19. **Test Case:** `[not keyboard-testable, raw curl]` With no auth token or signature of any kind, POST a crafted GRANTED consent to `/api/v3/consent/request/hip/notify` for a real patient/care-context, then POST a crafted `health_information_request` to `/api/v3/hip/health-information/request` with `dataPushUrl` pointed at an attacker-controlled URL and `keyMaterial` containing an attacker-generated public key.
    **Expected:** Rejected — these endpoints should only ever be reachable by ABDM's own gateway. **Suspected:** The server builds the real patient's FHIR bundle, encrypts it to the attacker's key, and POSTs it to the attacker's URL. **This is the single most important finding in the entire document** — full PHI exfiltration via two unauthenticated HTTP requests, with no signature/HMAC/allowlist check anywhere in the callback router. **[CRITICAL — recommend treating this as a priority fix, not just a documented test case, before this ever leaves a sandbox context]**

20. **Test Case:** Related to #19 — inspect what's actually sent when the server pushes data: the outbound push includes `Authorization: Bearer <our real ABDM gateway token>`, sent to whatever `dataPushUrl` the (unauthenticated) inbound request specified.
    **Expected:** Our gateway credential never leaves ABDM-controlled infrastructure. **Suspected:** Our gateway bearer token is sent to an attacker-supplied URL — beyond PHI exposure, this also leaks a live ABDM credential to a third party, and the URL itself is a straightforward SSRF vector (e.g. pointed at an internal/metadata address) since there's no scheme/host allowlist. **[CRITICAL, same root cause as #19]**

21. **Test Case:** `[not keyboard-testable, requires generating a specific crafted EC point]` Craft `keyMaterial.dhPublicKey.keyValue` as a low-order Curve25519 point (Curve25519 has cofactor 8, so several small-order points exist that are technically "on the curve" but never checked for beyond that), and submit a health-information request using it.
    **Expected:** Rejected as an invalid/dangerous key. **Suspected:** The curve-membership check exists but doesn't reject known low-order points — for at least one such point, the shared-secret arithmetic silently produces a predictable result rather than erroring, meaning an attacker-chosen key can force a **predictable encryption key**, making the "encrypted" bundle trivially decryptable. **[HIGH, cryptographic correctness issue]**

22. **Test Case:** Trigger a data push for a consent covering **2 or more** care contexts (any real multi-record patient works) and inspect the resulting `entries[]` in `storage/api_capture/m2_*.jsonl`.
    **Expected:** Distinct encryption per entry. **Suspected — already flagged at the top of this document:** the same ephemeral key material (hence the same derived AES key and IV) is reused across every entry in one transfer. This is confirmed via direct code reading, not just theory — worth confirming empirically by inspecting the actual captured ciphertexts for repeated key material. **[CRITICAL]**

23. **Test Case:** Force a condition where the outbound public-key-to-X.509 conversion fails (this is called completely outside any try/except in the push-preparation code).
    **Expected:** Reported as an ERRORED status for the affected care contexts, with a FAILED notify still sent to ABDM. **Suspected:** The exception escapes the whole push-and-notify function — **no push, no session update, and no notify to ABDM at all.** ABDM and the HIU are left waiting on a transfer that will never be reported as anything, success or failure. **[HIGH]**

24. **Test Case:** Push an entry with an empty/zero-length FHIR bundle (as opposed to zero *entries*, which is already guarded elsewhere).
    **Expected:** Handled the same as the already-guarded "no records" case. **Suspected:** Encrypts and pushes fine as a technically-valid-but-empty entry — worth confirming ABDM's tolerance for this rather than assuming it's harmless. **[LOW]**

## E. Bracket-access / malformed-payload crash inventory

*Every M2 callback handler mixes `.get()` (safe) and direct bracket access (`body["x"]`, unsafe) inconsistently. Because every handler's outer exception handler swallows the crash and the router always returns 200 "OK" to ABDM regardless (see START HERE #6), every single one of these — if hit for real — looks identical from ABDM's side to a fully successful, silent no-op. That shared consequence is arguably a bigger issue than any individual missing field check.*

25. **Test Case:** `[not keyboard-testable, raw curl]` POST a `discover` callback with the `patient` key omitted entirely, and separately with `"patient": null`.
    **Expected:** A clean "malformed discover request" rejection. **Suspected:** `KeyError` (omitted) or `AttributeError` (null) — either way, swallowed silently per the pattern above. **[MEDIUM]**

26. **Test Case:** `[not keyboard-testable]` Send `verifiedIdentifiers` as a list of bare strings instead of `{type, value}` objects.
    **Expected:** Same clean rejection. **Suspected:** `AttributeError` mid-loop. **[LOW-MEDIUM]**

27. **Test Case:** `[not keyboard-testable]` Send a `link/care-context/confirm` callback body that's missing `otp_txn_id`/`abha_address`/`selected_patient_records` — plausible if an older-schema session record is ever read back after a code change.
    **Expected:** Clean rejection with a specific "session schema mismatch" style message. **Suspected:** `KeyError`, swallowed. **[LOW]**

28. **Test Case:** `[not keyboard-testable]` Hand-edit a `care_context_link`/`care_context_notify` pending-session record to remove a required field (`abha_address`, `care_context_hi_types`, etc.), then trigger the corresponding callback.
    **Expected:** Clean, specific failure. **Suspected:** `KeyError`, swallowed — same pattern throughout. **[LOW-MEDIUM]**

29. **Test Case:** Point `patient_records.csv` at a version missing an expected column (`referenceNumber`, `patient_reference`, etc. — there are several places across the patient-repository and FHIR-transformer code that index these columns directly rather than via `.get()`).
    **Expected:** A clear "data file schema error" at startup or on first use. **Suspected:** `KeyError` on the very first row processed, aborting the whole discover/confirm/build step for **every** patient, not just a malformed row. **[MEDIUM — this one's worth actually running since it's a plausible real mistake when someone edits the CSV by hand]**

30. **Test Case:** `[not keyboard-testable]` Add a second `patient_reference` under the same ABHA address + facility in `patient_records.csv` (simulating a multi-MRN patient at one facility) and run a link/notify flow.
    **Expected:** Each care context notified under its own correct patient reference. **Suspected:** The code takes whichever `patient_reference` appears *first* and applies it to every care context in the batch — every care context gets notified under the wrong patient reference for anyone whose first-seen row isn't representative. **[MEDIUM, plausible real data shape]**

## F. Orphaned pending state / no TTL

31. **Test Case:** Start Flow 5 (Link Token Generation) from the CLI, then kill the ngrok tunnel before the callback can arrive.
    **Expected:** The pending session eventually expires/cleans itself up. **Suspected:** None of the four pending-state stores (link tokens, care-context links, care-context notifies, consent requests) has any TTL or sweep — the row lives forever, complete with a **live link token and the patient's ABHA address in plaintext**, unless the happy path eventually completes. This is already visibly true in the current storage (several orphaned rows present from earlier testing). **[MEDIUM — real, present, and growing]**

32. **Test Case:** Force an exception partway through the care-context-link notify loop (e.g. via #28's hand-edited pending record) and confirm whether the pending record gets cleaned up anyway.
    **Expected:** Cleaned up regardless of success/failure. **Suspected:** The cleanup step is the very last line of the function — any earlier exception leaves the pending record orphaned permanently. **[LOW-MEDIUM]**

33. **Test Case:** Reuse a link token that's deliberately "old" (saved from an earlier session, not freshly generated) for Notify Care Context Update.
    **Expected:** Rejected with a clear "token expired, re-generate" message and the dead token then removed. **Suspected:** Link tokens have **no expiry logic at all by explicit documented design** ("reused indefinitely until ABDM's real behavior is confirmed otherwise"), and the function that would delete a dead token is, per a repo-wide check, **never actually called by anything** — so if ABDM does reject it, the system has no way to recover and will keep trying the same dead token on every future reuse-path call for that patient/facility. **[MEDIUM, and directly testable — just wait a while before reusing a saved token]**

34. **Test Case:** `[not keyboard-testable]` Launch the FastAPI server from a working directory other than the repo root, then run any flow that touches storage.
    **Expected:** All storage reads/writes land in the same place regardless of launch directory. **Suspected:** Some storage paths are resolved as **absolute** (repo-root-anchored) and others as **relative to the current working directory** — inconsistently, across different files in the same codebase. Launching from the "wrong" directory silently splits state into two different trees, and callbacks that depend on a pending session written by the other tree will report "no pending session found" even though the happy path genuinely ran moments earlier. **[MEDIUM, and a very plausible real mistake — e.g. if the server is ever launched by a process manager with a different cwd than expected]**

## G. Protocol sequencing / correctness

35. **Test Case:** Confirm which HTTP status code M2's `health_information_request`-ack endpoint actually expects vs. what every other M2 ack expects (this one path checks for 200; essentially everything else in M2 checks for 202).
    **Expected:** Consistent, or intentionally different with a documented reason. **Suspected:** If ABDM ever legitimately returns 202 here (matching the pattern everywhere else), the whole transfer silently aborts with no push and no notify — worth a direct confirmation of which status code the live sandbox actually returns for this specific endpoint. **[MEDIUM]**

36. **Test Case:** Mock or otherwise force the HIU's data-receiving endpoint to return 201/202/204 instead of exactly 200 on a successful push.
    **Expected:** Still counted as delivered. **Suspected:** Only an exact `200` counts as delivered — any other 2xx is recorded as ERRORED and a FAILED notify is sent to ABDM even though the HIU actually has the data. **[LOW-MEDIUM]**

37. **Test Case:** Force a mixed-outcome push (some care contexts encrypt/push fine, some fail) and check what `sessionStatus` gets reported to ABDM overall.
    **Expected:** Confirm this matches what ABDM's own schema actually expects for a partial-success transfer — this is called out in the code's own comments as an untested assumption. **[MEDIUM, worth a live confirmation]**

38. **Test Case:** Trigger a `health_information_request` for a consentId that was never found locally (already covered functionally in v1) and specifically check what happens with the resulting **empty** `statusResponses` array in the FAILED notify — the code's own comment flags this as an assumption ABDM accepts an empty array here, never confirmed live.

39. **Test Case:** Send a FAILED notify whose description string contains parentheses (the code deliberately avoids parentheses in one specific hardcoded string based on a single earlier live observation that ABDM rejected a parenthesized description as `ABDM-9999 "Invalid description"` — but this is explicitly flagged as "a working hypothesis," not a confirmed rule, and isn't applied everywhere a description string is built).
    **Expected:** Consistent handling. **Suspected:** Any other place a free-text description gets built (including ones built from raw exception messages, which very often contain parentheses/commas) could hit the same rejection unnoticed. **[MEDIUM, worth a direct confirmation test]**

40. **Test Case:** Trigger a discover flow where the patient is matched by mobile number rather than ABHA address.
    **Expected:** ABDM's `matchedBy` field in the on-discover response accurately reflects that. **Suspected:** This value is hardcoded to `["MR"]` regardless of which identifier actually matched — flagged in the code's own TODO as unconfirmed whether ABDM cares. **[LOW, author-flagged]**

41. **Test Case:** Mutate/mock ABDM's "already linked" rejection message text slightly (different casing/wording) and confirm the "duplicate link, not a real error" detection still works.
    **Expected:** Still detected gracefully. **Suspected:** The detection matches on the literal English message string, not an error code (the documented code doesn't match what ABDM actually returns) — brittle to any future wording change on ABDM's side. **[LOW, author-flagged, already a known tradeoff]**

## H. FHIR builder edge cases

42. **Test Case:** Point a document/attachment record at a very large file (hundreds of MB).
    **Expected:** Streamed or rejected with a clear size-limit message. **Suspected:** Read fully into memory, base64'd (+33% size), embedded in a JSON body, encrypted, and held in the in-memory session store simultaneously — multiple full copies resident in memory at once for one attachment, with no cap anywhere. **[MEDIUM, worth confirming actual behavior at a large-but-realistic size like a 20-30MB scanned PDF]**

43. **Test Case:** Point a document record at a file path that doesn't actually exist on disk.
    **Expected:** That one record errors out (ERRORED status), the rest of the bundle still builds. **Suspected:** An unhandled `FileNotFoundError` aborts the **entire** bundle-build for **every** care context in the request, not just the one with the missing file. **[MEDIUM — easy to test: temporarily rename/move one sample attachment file]**

44. **Test Case:** Attach a `.png` image (X-ray, scan, etc.) rather than a `.pdf`/`.jpg`.
    **Expected:** Correct content-type. **Suspected:** The content-type mapper only knows pdf/jpg/jpeg — a PNG (or DICOM, or any other extension) falls back to `application/octet-stream`, which downstream FHIR renderers may not handle well. **[LOW-MEDIUM, easily testable]**

45. **Test Case:** Enter a blood-pressure-style observation as `"120/80/60"` (three numbers) or as free text like `"positive"` instead of a plain number.
    **Expected:** A clear validation error at data-entry time (in the dummy EMR generator) or a graceful skip. **Suspected:** Raw `ValueError` from an unguarded `float()`/unpack — this aborts the whole bundle build the same way #43 does. **[MEDIUM]**

46. **Test Case:** Enter an observation/procedure/diagnostic-report `status` field with unexpected capitalization (e.g. `"Final"` instead of whatever the exact expected value is) — unlike Encounter/Condition, which normalize their status fields against a known-valid set, several other resource builders pass status straight through unvalidated.
    **Expected:** Normalized or clearly rejected. **Suspected:** A pydantic/FHIR validation error deep inside bundle construction, in a spot with no direct "the status field was wrong" message. **[LOW-MEDIUM]**

47. **Test Case:** Set a chief-complaint/clinical-note field to include an ampersand, angle bracket, or actual HTML/script-like text (e.g. `Pain <script>alert(1)</script> & fever`), and separately to a non-English (e.g. Devanagari) string.
    **Expected:** Safely escaped in the generated FHIR narrative. **Suspected:** Interpolated **raw, unescaped**, into the XHTML narrative div — malformed XHTML at best, and a genuine stored-injection-shaped issue for any downstream renderer that trusts this content, at worst. **[MEDIUM-HIGH — this is a real correctness/safety gap in generated clinical documents, not just an edge case]**

48. **Test Case:** Enter a date of birth as a single-digit day (`1-10-1997`) or another non-two-digit-day format.
    **Expected:** Normalized correctly. **Suspected:** The birth-date parsing heuristic only recognizes a specific two-digit/two-digit/four-digit shape — anything else passes through unconverted into an invalid FHIR date, surfacing as a validation error with no indication the *date format* was the actual problem. **[LOW-MEDIUM]**

49. **Test Case:** Enter a practitioner with only a single-word name (no space) or a name with an unusual/non-English prefix.
    **Expected:** Handled gracefully either way. **Suspected:** A single-word name produces a null family name; the "Dr." prefix-stripping logic is English-only and has a couple of documented edge cases of its own (a name literally starting "Dr " without a period keeps the prefix). **[LOW]**

## I. Timeout / partial-failure gaps

50. **Test Case:** Repeat the earlier M1-style "network dies mid-call" test specifically for `send_on_discover()` — every one of these outbound calls uses a hardcoded 30-second timeout with **no retry logic anywhere**.
    **Expected:** A retry, or at least a clearly logged "ABDM never got this" state. **Suspected:** Logged and dropped — if ABDM genuinely never received the on-discover, the patient's PHR-app search for this record just silently fails with nothing on our side ever attempting redelivery. **[MEDIUM]**

51. **Test Case:** Kill the server process in the gap between `link_care_context()` returning 202 (link accepted) and the `on_carecontext` confirmation callback arriving.
    **Expected:** Some reconciliation on restart. **Suspected:** The link genuinely exists at ABDM's side, but the pending record that would trigger the follow-up Notify step (which is what actually makes the care context visible in the patient's PHR timeline) is now orphaned forever (§F1) — there's no reconciliation job anywhere that would catch "we have a stuck pending record older than X." **[MEDIUM-HIGH, a real gap in the happy-path-interrupted case]**

52. **Test Case:** Kill the server between a successful data push to the HIU and the follow-up "transfer complete" notify to ABDM.
    **Expected:** Retried or reconciled. **Suspected:** ABDM believes the transfer never happened (no notify ever arrived) even though the HIU genuinely has the data — and if this state is later "fixed" by a naive retry of the whole request, that retry re-pushes the same data under a new key (§B2), rather than just resending the missing notify. **[MEDIUM]**

53. **Test Case:** Two testers running Flow 5 concurrently for two different patients (a very plausible real scenario during a team testing session) — the CLI's own callback-polling helper for M2 correlates purely by label + arrival time, **not** by the specific request's own ID (contrast: the M3 CLI was specifically patched to add this correlation after hitting exactly this bug).
    **Expected:** Each tester sees only their own callback result. **Suspected:** Cross-matching — one tester's poll can pick up the other's callback, reporting a false success or false failure. **[MEDIUM, directly and easily reproducible — literally just have two people run Flow 5 at the same time, which is a realistic team-testing scenario]**

---

# M3 — HIU (Requesting Records from Other HIPs)

*Correction already flagged once, restating for completeness: M3 is fully implemented, not "not started" — and per its own commit history it has a materially shorter real-world testing history than M1/M2, which is itself a reason to weight this section's findings a bit more heavily than their individual severity might otherwise suggest.*

## A. Concurrency / correlation

1. **Test Case:** Fire two Block 2 (Health Information Request) calls for the same consentId within about a second of each other, from two terminals.
   **Expected — and this is a genuine positive finding, not a gap:** the server-side correlation (by our own generated REQUEST-ID / transactionId, not just label+time) is narrow enough that these two requests cannot cross-match each other server-side, unlike the CLI-level race that was already found and fixed once. Worth confirming this holds under a real concurrent run, since it's currently only verified by code reading. **[Confirm — low risk, but confirm]**

2. **Test Case:** `[not keyboard-testable, raw curl]` POST two `on-request` callbacks with **different** `response.requestId` values but the **same** `hiRequest.transactionId`, then push data for that transactionId.
   **Expected:** Rejected as a transactionId collision, or the two requests stay cleanly separated. **Suspected:** The transactionId-to-request-id index is last-writer-wins with no collision guard — the second callback silently overwrites the first's linkage. The practical consequence: a subsequent push gets decrypted with the *wrong* request's key material, fails AES-GCM authentication, and every care context in that push is reported ERRORED/"Decryption failed" **even if the HIP delivered the data correctly.** **[MEDIUM-HIGH — a plausible ABDM-retry-driven false failure, not just a crafted-attack scenario]**

3. **Test Case:** Push a bundle with many care-context entries (10-20+) and, at the same time, hit another callback endpoint or the `/health` endpoint from a second connection.
   **Expected:** No added latency on the concurrent request. **Suspected:** M3's decrypt step (same pure-Python Curve25519 arithmetic as M2's) runs directly on the event loop, not offloaded — measured at roughly tens of milliseconds per entry, meaning a large push measurably stalls every other in-flight request for the duration. **[MEDIUM-HIGH, and directly measurable if you want to actually time it]**

4. **Test Case:** `[not keyboard-testable]` Several concurrent `fetch_consent()` calls (a multi-artefact GRANTED notify) landing right as the cached gateway token nears its refresh window.
   **Expected:** One refresh. **Suspected:** Same last-writer-wins race as M1/M2 — N refreshes, possible spurious 401s. **[MEDIUM]**

5. **Test Case:** `[not keyboard-testable]` Same storage-corruption risk as M2 §A1/A5 — multiple processes (server, M2 CLI, M3 CLI) all append-writing the same underlying JSONL files with no lock. Script a burst of concurrent writes to `pending_health_information_requests.jsonl` specifically and check for corrupted/dropped lines afterward.
   **Expected:** No loss. **Suspected:** Silent record loss, presenting later as a confusing "no pending request found for transactionId X" — with real PHI-adjacent state (including private key material, see §E2) as the thing quietly dropped. **[HIGH]**

## B. A genuinely reproducible false-failure (worth running first in this whole module)

6. **Test Case:** Run Flow 2 (Health Information Request) against a consent covering several care contexts, ideally with at least one large attachment.
   **Expected:** "N care context(s) received and decrypted successfully." **Suspected — high confidence this is real, not hypothetical:** the CLI's callback-poll can observe that a push callback *arrived* (the raw capture-log entry is written before the handler even starts processing it) before the handler has actually finished decrypting/storing anything. Combined with real processing time (decrypt + notify round trip, up to a 30-second timeout budget), the CLI's very next step — checking whether anything got stored — can run **before** the store write happens, and will report **"Data push arrived but nothing was stored — check the server logs for a processing error"** on a transfer that is actually completing successfully a moment later. **[HIGH — please run this one specifically; if you see this exact failure message on what looks like an otherwise-clean run, this is very likely why, not a real processing bug]**

7. **Test Case:** `[not keyboard-testable]` Launch the server from a directory other than the repo root (same class of bug as M2 §F4) — the M3 api-capture directory path is resolved relative to the launch directory in one place and absolutely (repo-root-anchored) in the CLI's own polling code.
   **Expected:** Consistent regardless of launch directory. **Suspected:** Every `wait_for_callback()` in the M3 CLI times out forever even though the server is handling callbacks perfectly — the capture files just land in a second, different `storage/` tree the CLI never looks in. **[MEDIUM, but exactly the kind of thing that wastes a lot of debugging time if hit]**

## C. Consent lifecycle staleness (already partially flagged, expanding here)

8. **Test Case:** Grant a consent, complete Block 1, then revoke it from the patient's side, then run Block 2 (Flow 2)'s consent picker.
   **Expected:** The revoked consent disappears from the selectable list. **Suspected — already confirmed by direct code reading:** the stored consent status is only ever written once, at initial fetch time, and never updated on a later REVOKED/DENIED notification — so the picker still offers it, and Block 2 will attempt to request data against an artefact that's actually dead. **[HIGH, and directly testable if you have a way to revoke consent from the patient side of the sandbox]**

9. **Test Case:** Wait past a consent's own `dataEraseAt` timestamp (set it a couple of minutes in the future during Block 1 to make this practical to test), complete Block 2, then check whether the received data actually gets purged after that time passes.
   **Expected:** Purged. **Suspected:** Nothing anywhere reads or enforces `dataEraseAt` — it's stored and forgotten, meaning received PHI is retained indefinitely regardless of what the consent artefact itself says about retention. **[HIGH, compliance-flavored, and genuinely testable on a short timescale]**

10. **Test Case:** `[not keyboard-testable, raw curl]` POST a hand-crafted `on-fetch` callback directly, with a `consentId` and `consentDetail` you make up (e.g. a widened date range, or a `hip.id` for a facility you never actually had consent from).
    **Expected:** Rejected — an on-fetch callback should only be accepted in response to a `fetch_consent()` call we actually made. **Suspected:** This endpoint has **no correlation check of any kind** — it will store whatever `consentDetail` it's given under whatever `consentId` is given, no questions asked. Combined with the earlier unauthenticated-endpoint finding, this means the local date-range guard that Block 2 relies on (validating against the *stored* consent) can be fed a completely fabricated consent artefact and will happily "validate" against it. **[CRITICAL — same class as the M2 auth gap, and it directly undermines the one piece of local validation M3 does have]**

11. **Test Case:** Flip `HEALTH_INFORMATION_TRIGGER_MODE` to `"auto"` (currently dormant/default-off, and per the code's own history, essentially untested) and send two `on-fetch` callbacks for the same artefact.
    **Expected:** One Block 2 pull triggered. **Suspected:** In auto mode, every GRANTED on-fetch triggers its own Block 2 pull with no dedup — a duplicated on-fetch (ABDM retry, or the crafted-callback scenario in #10) causes a **second full live data pull** for data already retrieved. **[MEDIUM, low-likelihood only because this mode isn't the default, but worth knowing before ever flipping it on]**

## D. Block 2 data-push integrity

12. **Test Case:** `[not keyboard-testable, raw curl]` Send two pushes for the same transactionId with `pageCount: 2`, `pageNumber: 0` and `pageNumber: 1` respectively, each carrying different care contexts (the protocol explicitly supports paginated pushes).
    **Expected:** Both pages merged into one complete record. **Suspected:** Each push is a **whole-record overwrite** keyed only by transactionId — page 0's data is silently destroyed the moment page 1 arrives, and a separate "received" notify is sent to ABDM for each page independently as if it were the whole transfer. **[HIGH — real data loss if ABDM ever actually paginates a push, which the protocol clearly anticipates it might]**

13. **Test Case:** `[not keyboard-testable, raw curl]` Push an entry whose `careContextReference` doesn't correspond to anything in the actual consent scope for that transaction.
    **Expected:** Rejected as out-of-scope. **Suspected:** Nothing checks a pushed entry's care-context reference, hiType, or date against what the consent artefact actually authorized — it's decrypted and stored as if it were legitimately in scope. **[HIGH, a genuine consent-scope/data-integrity gap]**

14. **Test Case:** `[not keyboard-testable]` Push a request whose `entries` array contains one malformed item (e.g. `content` as a number instead of a string) alongside otherwise-valid entries.
    **Expected:** The malformed entry is skipped/errored; the valid entries still get processed and stored. **Suspected:** The malformed-entry guard only covers a couple of specific missing-field cases — a genuinely wrong-typed field throws an exception that escapes the per-entry handling and aborts the **entire push**, losing the good entries along with the bad one. **[MEDIUM-HIGH]**

15. **Test Case:** Force a decryption failure (e.g. via a wrong-format key per §F below) and inspect the resulting FAILED-notify description text sent to ABDM.
    **Expected:** A clean, generic failure description. **Suspected:** The description is built directly from the raw Python exception message, which can easily contain parentheses/commas — and M2's own code comments already document that ABDM has, at least once, rejected a parenthesized description as invalid. If that happens here, the FAILED notify itself fails, and (per the exception-swallowing pattern) that secondary failure is invisible too. Bonus concern: this also leaks internal crypto implementation details in the description text sent to ABDM. **[MEDIUM, concretely testable]**

16. **Test Case:** `[not keyboard-testable]` Delete/lose the pending session record for a transactionId (e.g. via the storage-corruption scenario in §A5), then have the HIP push data for it anyway.
    **Expected:** The HIP is told to retry (a 4xx/error response) since we can't process it. **Suspected:** The push handler returns early and the route still acks 200 "OK" to the HIP — the HIP believes the push succeeded, the data is permanently discarded on our side, and no notify is ever sent to ABDM either. The transaction just quietly disappears from everyone's view except a log line. **[MEDIUM]**

## E. Security / trust boundary

17. **Test Case:** Same class of finding as M2's — the `/api/v3/hiu/health-information/push` endpoint (a fixed, guessable path on the same public ngrok URL) has no authentication despite the HIP side legitimately sending a bearer token that we simply never check.
    **Expected:** Rejected without valid auth. **Suspected:** Anyone who can guess/observe the push URL (visible in logs and api_capture) and has a leaked transactionId can push arbitrary "patient data," encrypted to our own already-known public key, and have it stored and reported to ABDM as a genuine delivery. **[CRITICAL, same root cause as the M2 finding — recommend addressing both together, not as two separate fixes]**

18. **Test Case:** Check how long ECDH private key material sits in plaintext storage after a transaction completes.
    **Expected:** Deleted promptly after use. **Suspected:** Nothing in M3 ever deletes a pending request record — the delete function exists but, per a repo-wide check, is never actually called from anywhere. Private keys (plus the nonce) for every Block 2 request accumulate in plaintext, forever, alongside the encrypted ciphertext of the same transaction already archived in the capture logs — meaning anyone with filesystem access to `storage/` can decrypt every historical transfer this HIU has ever made. **[HIGH, and a good one-time housekeeping/retention question independent of any fix]**

19. **Test Case:** Confirm what's actually written to `storage/hiu_health_information.jsonl` and the M3 CLI's own run logs after a normal Flow 2 run.
    **Expected:** Redacted/summarized. **Suspected:** Full decrypted PHI (already confirmed present, ~125KB across 9 records from testing so far) with no erase job (ties to §C2/§C9), plus the CLI's own logs additionally writing full callback bodies to disk per run. **[MEDIUM, same policy-question flavor as the M1 secrets-on-disk finding]**

## F. Key-material format / interop

20. **Test Case:** `[not keyboard-testable, needs a crafted request or a real 3rd-party HIP]` Send a push whose `keyMaterial.dhPublicKey.keyValue` is a **raw** (non-X.509) 65-byte public key — i.e. the same format M3 itself sends on the way *out*.
    **Expected:** Accepted (or clearly rejected with a specific "wrong key format" message). **Suspected — this is the START HERE #7 item, restated with its concrete trigger:** the incoming-key path unconditionally assumes X.509 DER and provides no raw-format fallback, while the outgoing-key path deliberately sends raw. A real third-party HIP that (reasonably) mirrors our own outbound convention will have **every single data push from them rejected outright** — "could not decode HIP's public key" on 100% of entries. **[HIGH — recommend this become a fix, not just a test case, before ever testing against a genuinely independent HIP rather than our own self-referential HIP+HIU sandbox setup]**

21. **Test Case:** Delay a push until after its key material's stated expiry window has passed.
    **Expected:** Rejected as expired. **Suspected:** The expiry timestamp is generated and stored but nothing on the receiving side actually checks it — a very late push is decrypted exactly as if it arrived on time. **[LOW-MEDIUM]**

22. **Test Case:** `[not keyboard-testable]` Send a push whose `keyMaterial.cryptoAlg` field says something other than `"ECDH"` (e.g. `"RSA"`) while the actual key bytes are still ECDH-shaped.
    **Expected:** Rejected as an algorithm mismatch. **Suspected:** `cryptoAlg`/`curve` are never actually checked — the declared algorithm is ignored and the bytes are processed as ECDH regardless of what they claim to be. **[LOW]**

## G. Malformed-payload / bracket-access inventory

*Same pattern as M2: mostly `.get()`-guarded, with a handful of residual bracket-access or unguarded-type-assumption spots.*

23. **Test Case:** `[not keyboard-testable]` Send a `consent_hiu_notify` callback where `consentArtefacts` is a list of bare ID strings rather than `{id: ...}` objects — a plausible shape variant.
    **Expected:** Handled gracefully. **Suspected:** `AttributeError` mid-loop, and because this happens *before* the acknowledgement step, **ABDM never receives any ack for this notification at all** — silence, not even a "we tried and failed" signal. **[MEDIUM]**

24. **Test Case:** `[not keyboard-testable]` Inject a consent artefact (via the same unauthenticated-on-fetch path as §C10) with `"permission": null` explicitly, then run Block 2's date-range validation against it.
    **Expected:** A clean "no approved date range to validate against" message, same as the already-existing guard for a missing `dateRange`. **Suspected:** This specific field isn't guarded the same way its siblings are — a raw `AttributeError` escapes the validator as something other than the expected `DateRangeValidationError` type, which means the CLI's own re-prompt-on-validation-failure loop doesn't catch it and the whole flow crashes instead of cleanly re-prompting. **[MEDIUM, and a good one to run since it's a real inconsistency in an otherwise well-guarded function]**

25. **Test Case:** Enter a valid ISO-8601-*looking* date at the Block 2 date prompt but **without** a timezone offset or trailing `Z` (e.g. `2026-01-01T00:00:00` rather than `2026-01-01T00:00:00Z`) — this is exactly the kind of thing a person might type from memory.
    **Expected:** Handled the same as any other date, or rejected with a clear "must include timezone" message.
    **Suspected — verified by direct reasoning about Python's datetime comparison rules:** this parses successfully as a naive (timezone-unaware) datetime, so it slips past the existing parse-error check, but then crashes with a raw `TypeError` when compared against the consent's timezone-aware stored range — a completely different, uncaught failure from the "bad format" case the validator otherwise handles well. Also affects the dormant `auto`-trigger-mode code path, where it would just be a swallowed log line instead of a visible crash. **[HIGH — easily keyboard-testable, and a very plausible real typo, not a contrived one]**

## H. Multi-artefact consent grant sequencing

26. **Test Case:** `[not keyboard-testable, needs network interception]` Grant a consent that spans multiple HIPs/artefacts in one notification, and force a network failure partway through fetching the 2nd of 3 artefacts.
    **Expected:** Artefacts 1 and 3 still get fetched; a partial-success ack goes to ABDM either way. **Suspected:** There's no per-artefact error isolation — a failure on any one artefact aborts the whole loop, meaning artefacts after the failed one are never even attempted, **and ABDM never receives any acknowledgement for this notification at all** (the ack step comes after the loop, so it's skipped too). From ABDM's perspective, we simply never responded to a grant we actually partially processed. **[HIGH]**

27. **Test Case:** `[not keyboard-testable]` POST a notify for a `consentRequestId` that has no matching earlier on-init record locally (plausible if on-init was itself dropped/delayed — a real ordering risk since notify and on-init are independent deliveries with no guaranteed order).
    **Expected:** Queued/retried once the on-init information becomes available. **Suspected:** Permanently unresolvable — the code logs "cannot resolve our hiu_id" and skips straight to sending ABDM an **OK acknowledgement anyway**, for artefacts that were never actually fetched. There's no re-resolution path if the missing on-init arrives later. **[MEDIUM-HIGH]**

28. **Test Case:** Grant a consent spanning 5 artefacts against a slow/throttled sandbox and time how long the whole notify callback takes to process.
    **Expected:** Bounded, reasonably fast. **Suspected:** Artefacts are fetched strictly sequentially, each with its own 30-second timeout budget — a 5-artefact grant under real slowness could take up to two and a half minutes inside one callback handler, well past what ABDM's own gateway is likely to wait before considering the callback itself failed/timed-out. **[MEDIUM]**

## I. No timeout/alerting if the other side goes silent

29. **Test Case:** Complete Block 2's on-request step successfully, then simply never have the HIP actually push any data (or block the HIP's ability to reach our push URL).
    **Expected:** Some eventual failure signal — a timeout, an alert, a status change visible somewhere. **Suspected:** Nothing. There's no timer, no scheduled sweep, no eventual FAILED notify sent to ABDM on our own initiative — the only signal that anything is wrong is the interactive CLI's own 90-second poll timeout, and that's only useful if a human happens to be sitting at that specific CLI session watching it. If Block 2 was triggered automatically (auto mode) or the CLI was closed, the request just hangs forever with zero visibility. **[HIGH, and a good one to actually run — start Block 2, then deliberately don't let the push happen, and see what evidence exists anywhere that something is stuck]**

30. **Test Case:** Same question for Block 1 — start a Consent Init Request and simply never grant it from the patient side.
    **Expected:** Some way to see/cancel outstanding requests later. **Suspected:** No expiry, and the CLI itself has no "list my outstanding consent requests" or "check status" flow at all — once you've fired the request, the only way to know what happened is to have been watching the server console at the time. **[MEDIUM]**

## J. CLI-specific

31. **Test Case:** Test Consent Init Request (Block 1) against a facility with zero linked practitioners **and** an empty overall practitioner list (temporarily rename `practitioners.csv` to simulate).
    **Expected:** A clear "no practitioners available" message. **Suspected:** The practitioner-selection prompt has no empty-list guard the way the equivalent patient/care-context selectors elsewhere in this codebase do — with nothing to select, the "type a number in range" loop has no valid input it will ever accept, so it loops forever with no way out except Ctrl-C. **[LOW likelihood in practice, but a real gap and easy to verify]**

32. **Test Case:** Compare the CLI's requester `registration_system` value (currently a plain council name like "Gujarat Medical Council") against what ABDM's own confirmed example expects (a URL) — flagged in the code itself as "untested either way."
    **Expected/Suspected:** Genuinely unknown — this is exactly the kind of "go run it and tell me" case the code's own comments are explicitly asking for. **[AUTHOR-FLAGGED, please run once]**

33. **Test Case:** Run each of the 6 consent-purpose options (Care Management, Break the Glass, Public Health, Healthcare Payment, Disease Specific Healthcare Research, Self Requested) through a real Consent Init Request. Only "Self Requested" has been independently confirmed against a real ABDM example; the other 5 code→display-text pairings were inferred from a table whose formatting merged some rows on export.
    **Expected:** All 6 work identically. **Suspected:** Unconfirmed for 5 of 6 — worth a one-time sweep rather than assuming they're all fine because one is. **[AUTHOR-FLAGGED]**

34. **Test Case:** Run Block 2 against a patient/consent whose care contexts include the larger sample attachments (the ones added alongside the M3 implementation itself) and see whether the CLI's fixed 90-second poll timeout is actually enough headroom given realistic decrypt+notify time for a bigger transfer.
    **Expected:** Comfortably within budget. **Suspected:** Possibly not, once a real multi-entry, large-attachment transfer is timed end-to-end — worth just running once and checking the actual elapsed time against the 90s ceiling. **[LOW-MEDIUM]**

---

# Best-Practice Observations (cross-cutting, not individual test cases)

- **No shared validation layer anywhere** in M1/M2/M3 — every module sends whatever it's given straight to `requests.post()`. The one deliberate exception (M3 Block 2's local date-range check) is a good model; a small shared validators module (digit/format checks, ISO-8601 + ordering checks, a "does this look like a real identifier" pass) would close a large fraction of both the v1 and v2 findings in one pass rather than field-by-field.
- **The "swallow the exception, still tell ABDM OK" pattern is the single biggest amplifier of severity in this whole document.** Almost every malformed-payload finding across M2 and M3 would be a minor, self-evident bug if it surfaced as a visible error — instead, because every service-level handler catches broadly and the router always acks 200, these failures are invisible unless someone is actively grepping log files. Fixing the ack/error-signaling pattern once would make dozens of the individual findings above self-diagnosing instead of silent.
- **No storage-layer locking or compaction anywhere.** This was flagged as a known, accepted risk in the storage module's own docstring — worth revisiting now that both M2 and M3 lean on it under genuinely concurrent, async, multi-process usage (server + multiple CLI test suites running side by side), which is a meaningfully different risk profile than when that tradeoff was likely first made.
- **No authentication on any inbound ABDM callback endpoint.** This is the highest-severity item in the whole document (see START HERE #1) and is worth treating as a fix, not just a test case, before this code is ever reachable outside a fully trusted sandbox context.
- **Consent lifecycle state (M2 and M3 both) only ever moves forward on the happy path** — grants are recorded, but revokes/denials/expiries are either not recorded (M3) or can be raced by an out-of-order replay (M2). A more defensive design would treat every consent-status update as authoritative-and-versioned rather than "overwrite on GRANTED, otherwise ignore."
