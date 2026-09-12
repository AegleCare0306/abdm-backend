# CC Prompt P18 — Health Locker / Subscription / Auto-Renewal: start over, register the service, reuse code but not conclusions

## Trigger (Aayush, verbatim, 2026-09-09)

He found the likely root cause of the R2 Health Locker blockage himself: *"Go through the Gateway folder in
Postman. We have to register the Service as a PHR and health locker. And then in the Subscriptions folder
we need to first run the Setup locker API before anything else."*

Then, when asked to write this up, he gave an explicit reframing instruction that governs the whole chunk,
verbatim: *"tell it to not restrict itself [to] what is already built for the Health locker, subscription
and auto renewal. It should be like we are starting from scratch. Everything we thought or assumed before
can be wrong. We start with that approach and reuse any code or logic that was already [built] for this,
but we don't restrain ourself [because] the code is like this [so we assume] that's how it is."*

## THE MOST IMPORTANT INSTRUCTION IN THIS PROMPT — read this before touching anything

Everything this project has previously concluded about Health Locker, Subscription Flow, and any renewal/
expiry behavior — including things stated as "CONFIRMED" or "RESOLVED" in prior memory/prompts — is a
**hypothesis to re-verify, not a settled fact**, for the specific duration of this chunk. That includes:

- **R2 was marked "RESOLVED IN THE NEGATIVE"** (this ABDM sandbox account supposedly lacks Health
  Locker/Subscription access, requiring an ABDM-side support-channel grant). That conclusion was reached
  from a uniform HTTP 400 across every `hiu.id` tried on subscription-init — but nobody had checked
  whether the service was ever actually *registered* as a Health Locker/PHR at the Gateway level in the
  first place. **Treat R2's "negative" resolution as unconfirmed, not true**, until you've actually tried
  registering the service and re-testing.
- **`hiu.id = CLIENT_ID` (`SBXID_046112`) for subscription/Health Locker calls** — this pattern was
  copied from Data Flow and Subscription's own HIU role by precedent, not verified specifically for the
  Health Locker actor type. Re-derive it, don't assume it transfers.
- **`X-LOCKER-ID = CLIENT_ID`** — currently just a placeholder hint in the UI (`SBXID_046112`), never
  actually tested (see below — Setup Locker has never once been submitted live). Don't treat it as
  confirmed just because it's the value sitting in a text field.
- **8.3.14's URL correction** (using Postman's path over the spec's, which looked like a copy-paste
  duplicate) — re-confirm this is still the right call once you're looking at the whole picture fresh.
- **Whether the 18-item Subscription Flow build (P13) is actually complete and correctly sequenced** —
  it was built against the spec's own item list without registration as a precondition. Now that
  registration looks like it was the missing prerequisite the whole time, re-examine whether anything
  P13 built needs to *change*, not just "needs to be exercised live for the first time."
- **Whether there's an "auto-renewal" concept at all, and if so what it actually is.** This has not been
  investigated by this project at any point before now. Do not assume it exists (there's no such item
  in the spec's 18-item list surveyed so far) and do not assume it doesn't (that survey may itself have
  been incomplete — see the research step below). Go find out fresh.

**What "reuse code, not conclusions" means concretely**: the actual working infrastructure below is real
and should NOT be rebuilt — it's just infrastructure, not a design decision:
- `get_gateway_token()` / `generate_gateway_token()` (`repo/server/auth.py`, `repo/server/utils.py`) — a
  working, cached client-credentials Gateway bearer token. Reuse it as-is.
- `find_bridge_service_by_id()` / `find_services_by_bridge_id()` (`repo/server/auth.py`) — working GET
  lookups against the Gateway's bridge-service endpoints. Reuse them as-is for the discovery step below.
- `aegle_phr/phr/subscription.py`'s 21 functions, `setup_locker()` included — this is real, tested
  plumbing for making Subscription/Health-Locker API calls. Reuse it. But do NOT assume its current
  call-order, header values, or "what happens next" logic reflects the correct design just because it's
  what's already there — re-derive that part fresh per the instruction above.

## The concrete lead: Gateway's bridge-service registration endpoint

Confirmed directly in Postman (PHR collection, "Gateway" folder, item `v3/gateway/bridge-service`):

```
PUT {{base-url}}/api/hiecm/gateway/v3/bridge-service
Headers: REQUEST-ID, TIMESTAMP, X-CM-ID, Authorization: Bearer {{BEARER_AUTH}}
Body: {
  "bridgeId": "...",
  "serviceId": "...",
  "name": "...",
  "isHip": true,
  "isHiu": true,
  "isHealthLocker": null,
  "isPhr": false,
  "endpoints": {},
  "attributes": null,
  "active": true
}
```

Confirmed by direct grep of both repos: **nothing anywhere calls this endpoint.** The only Gateway calls
that exist today are the two read-only GET lookups above and an unrelated Health Facility Registry POST
(`facility.py::register_bridge_service()`, which despite its name hits a completely different ABDM
endpoint/domain — do not confuse the two). This project's own convention (confirmed via
`facility.py:78` and a comment in `aegle_phr/phr/data_flow.py:334`) is that `CLIENT_ID` (`SBXID_046112`)
is our `bridgeId`. There is **no established `serviceId` anywhere in this codebase** — resolving that is
the first real step (see below).

**A related, still-unresolved loose end from an earlier session**: `repo/.env` and `repo/server/
config.py` (lines ~60-71) already carry a second, unverified credential pair —
`PHR_CLIENT_ID=SBXID_073333` / `PHR_CLIENT_SECRET` — added 2026-09-07 by a prior Claude Code session
specifically because it suspected the primary `CLIENT_ID` might lack HIU/PHR role provisioning. Nothing
reads it yet. Now that the bridge-service registration gap looks like the real explanation, decide for
yourself, based on what you actually find, whether this second identity is still relevant or a dead end
— and either way, make an explicit decision and say so, don't just leave it sitting there unused and
unexplained for a third session to wonder about.

## What Setup Locker actually is today

`aegle_phr/phr/subscription.py::setup_locker()` (~line 469) is real, wired code — `POST
/phr/subscription/setup-locker` → `SubscriptionsScreen.tsx`'s "Setup Locker" button, free-text
`X-LOCKER-ID` field (placeholder-hinted `SBXID_046112`, not auto-filled). **Confirmed via a full grep of
every log file in both repos, every date: it has never once actually been submitted.** The button exists;
there is zero log evidence it was ever clicked and its request reached the server. So "run Setup Locker
first" is not a retry of something that failed before — it's the first real attempt.

## Plan

1. **Fresh research first, before writing any code.** Re-read spec §4 (Gateway — flagged in project memory
   as "likely nothing left to build," never actually confirmed) and §8 (Subscription/Health Locker) with
   fresh eyes, specifically looking for: any documented registration/onboarding step for Health Locker or
   PHR service type, anything about subscription renewal/expiry/auto-renewal, and anything that would
   settle what `serviceId` should be. Cross-reference Postman's PHR collection AND the separate "ABDM
   Collection" reference workspace — specifically its "Getting Started" folder ("Check your configuration",
   "Linking HIP/HRP", "Register callback url") which has not been opened yet in this project and may
   document the registration step order directly. Report what you find before building anything, including
   if you find nothing — a clean "spec/Postman is silent on X" is a real, useful finding, not a failure.

2. **Discover current registration state, live, read-only, before changing anything.** Add a small new
   flow to `repo/tools/m2_test_suite/flows/bridge_gateway.py` (this tool's own established home for
   Gateway/bridge admin flows) that chains the existing `find_services_by_bridge_id()` (to get whatever
   `serviceId`(s) are on file for `bridgeId=CLIENT_ID`) into `find_bridge_service_by_id()` for each one
   found (to get the current `isHip`/`isHiu`/`isHealthLocker`/`isPhr`/`endpoints`/`active` values). Run it
   live. Report the exact current state before touching anything.

3. **Register/update the service.** Add a new flow (same file) that PUTs `bridge-service` with
   `isHealthLocker: true` and `isPhr: true` — but do NOT blindly copy Postman's example body. Use the
   `serviceId` actually discovered in step 2, and preserve whatever `isHip`/`isHiu`/`endpoints`/`active`
   values step 2 found rather than guessing new ones (this is an update to an existing registration, not a
   fresh one — getting this wrong could disturb the working HIP/HIU registration that Data Flow, Consent
   Manager, and HIP-Initiated Linking already depend on, so treat the existing values as load-bearing and
   only add the two new flags). Reuse `get_gateway_token()` for auth. Run it live, report the raw result.

4. **Re-confirm.** Re-run step 2's check-registration flow and confirm the change actually stuck.

5. **Only then, re-test Setup Locker live**, for the first time ever, with whatever `X-LOCKER-ID` value
   your step-1 research says is correct (start with the `CLIENT_ID` hint already in the UI if research
   doesn't turn up something more specific, but don't treat that as gospel).

6. **Re-test the Subscription Flow's `subscription-init` end to end, live** (the same call that produced
   the uniform 400s on 2026-09-03), and see whether registering the service actually unblocks it.

7. **Fix a diagnosability gap you'll otherwise hit immediately**: `subscription.py::_execute()` currently
   logs only the HTTP status code to the plain-text server log (`log_api_call(description, url,
   response.status_code)`) — the full response body only goes to `aegle_phr`'s own Postgres
   `abdm_call_log` table via `archive()`, which is not reachable from outside that machine's own local
   network (confirmed this session — Cowork's device bridge cannot reach `localhost:5433` on Aayush's
   machine). Add a truncated, secret-redacted response-body line to the plain-text log for calls made
   during this chunk's live testing (at minimum for the new bridge-service/setup-locker/subscription-init
   calls), so a future session can diagnose a failure from the log files alone rather than needing direct
   Postgres access.

8. **Auto-renewal — genuinely new research, don't skip it and don't assume an answer going in.** Once the
   above either works or doesn't, use whatever step-1 research turned up (plus anything the live 400/200
   responses reveal) to determine whether a subscription/Health-Locker grant here actually has an expiry
   or renewal mechanism at all, and if so what it is. Only design/build something for it if you find a
   real, spec-or-Postman-documented mechanism — report clearly if you conclude there isn't one.

## Verification

Offline: confirm the new flows exist in `bridge_gateway.py` and match this plan; confirm nothing about
already-working flows (HIP-Initiated Linking, Data Flow, Consent Manager, existing subscription-init
call sites) was touched except where step 3 explicitly requires it.

Live (ask before each, report the raw result of each): step 2's discovery, step 3's registration PUT,
step 4's re-confirmation, step 5's Setup Locker, step 6's subscription-init retry, and whatever
auto-renewal testing step 8 concludes is actually needed.

## Constraints (standing, unchanged)

Never delete or truncate anything under `logs/`/`storage/`. No git commit/push/init. Never print secrets
or tokens (including the Gateway bearer token itself) into any report. This chunk touches `repo/`'s own
admin tooling (`tools/m2_test_suite/flows/bridge_gateway.py`) and `aegle-phr`'s `subscription.py` — both
allowed here under Aayush's direct, explicit instruction for this specific chunk, not as a general
license to modify either repo's product code going forward.

## Reporting back

For every live step, report the exact request made and the exact result (status + whatever of the body
is safe to show). Be explicit about which of your findings **confirm** something this project previously
believed versus **correct** it — per Aayush's own instruction, a correction here is not a failure, it's
the point of starting over.

## Model recommendation

Sonnet, extended thinking ON — this chunk touches a live registration/authorization boundary shared by
every other already-working flow in `repo/` (HIP-Initiated Linking, Data Flow, Consent Manager all depend
on the same bridge-service registration not being disturbed), plus a genuine "re-derive from scratch"
research task, both of which warrant it per this project's own established model-guidance pattern.
