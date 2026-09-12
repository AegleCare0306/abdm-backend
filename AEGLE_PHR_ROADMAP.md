# Aegle Care — PHR App (M4) Roadmap

**Status:** Pre-development planning
**Date:** 2026-08-27
**Source spec:** `ABHA_PHR_V3_Documents` v1.1 (28.04.2025) — 12 sections, ~90 endpoints
**Decisions taken:** all ABDM blocks in scope · **one** client ID (`SBXID_046112`), **one** callback URL, **one** fixed ngrok host · shared code extracted to an installable `aegle-abdm-core` package · throwaway Vite+React test UI on Vercel

> **Revision 2 (2026-08-27):** R1 was originally written as a Phase-0 blocker. That was wrong. On a full pass over the spec's callback inventory, **phases P0–P4 need no colliding callback at all** — the entire patient-side consent flow is polling plus direct REST, with no callbacks. Collisions begin at P5. R1 is re-rated and the phase plan adjusted. Three new documentation gaps (R11–R13) surfaced during the same pass.

---

## 1. What we are actually building

The PHR app is **not** a fourth milestone of the same kind as M1/M2/M3. It is a *different actor* in the ABDM ecosystem, and it plays three roles at once:

| Role | Spec sections | What it means | Relationship to existing repo |
|---|---|---|---|
| **A. PHR / ABHA-address client** | §3 | Owns the patient's ABHA *address* (`name@sbx`) — enrollment, login, profile. Talks to `abhasbx.abdm.gov.in/abha/api/v3/phr/app/*` | Brand new. M1 handles ABHA *numbers*; this handles ABHA *addresses* under a different URL tree and a different auth model. |
| **B. Patient-side HIE-CM client** | §5, §6, §10 | The patient's agent: discovers records, links them, grants/denies/revokes consent, shares profile at a facility. Sends `X-HIU-ID`. | Mirror image of what M2 already implements from the HIP side. Our HIP and our PHR will be able to talk to each other. |
| **C. Health Locker / HIU** | §7, §8 | Subscribes to a patient's record stream, auto-requests consent, pulls and stores the data. | Substantially covered by existing M3 HIU code (`hiu_consent.py`, `hiu_health_information.py`, `fidelius_crypto.py`). |

**The single most valuable consequence:** once role B exists, you can run **the full ABDM triangle inside your own two repos** — your PHR raises a discover against your own HIP (`IN3310002215` / `IN2410002590`), the HIP answers, the patient links, a consent is granted, and data flows. Today you can only test each half against ABDM's own reference app.

---

## 2. Hard prerequisites — resolve before Phase 1

### 2.1 Callback disambiguation — deferred to P5, not a Phase-0 blocker

One client ID, one callback URL, one ngrok host is a settled decision. That means the EMR backend and the PHR backend share a single registered address (`PATCH /api/hiecm/gateway/v3/bridge/url` takes one `url` per `clientId` — verified in §4.2.4 and in `server/auth.py`). Everything ABDM sends you arrives at the same front door.

**The good news, and a correction to revision 1 of this document:** that front door only becomes ambiguous late.

Because the PHR-as-Health-Locker is *also* an HIU, four callback paths it eventually needs are already claimed by the existing repo's M3 HIU code (verified against `server/callbacks/router.py`):

| Colliding path | Existing owner | PHR also needs it for |
|---|---|---|
| `/api/v3/hiu/consent/request/on-init` | M3 Block 1 | Locker raising consent on a `LINK` notification (§8.1) |
| `/api/v3/hiu/consent/request/notify` | M3 Block 1 | Same |
| `/api/v3/hiu/consent/on-fetch` | M3 Block 1 | Same |
| `/api/v3/hiu/health-information/on-request` | M3 Block 2 | Locker pulling data (§7) |

**But none of those four is needed before P5.** Every PHR callback in phases P0–P4 has a path the EMR backend never uses:

| Phase | PHR callbacks needed | Collides? |
|---|---|---|
| P0–P2 (auth, profile) | *none* — all synchronous REST | — |
| P3 (UIL) | `/api/v3/hiu/patient/care-context/on-discover`, `on-init`, `on-confirm` | No |
| **P4 (consent, patient side)** | ***none*** — see below | **No** |
| P5 (data flow as requester) | `/api/v3/hiu/health-information/on-request` | **Yes** |
| P6 (locker) | subscription paths (no clash) **+** the three consent paths | **Yes** |
| P7 (profile share) | `/api/v3/hiu/patient/on-share` | No |

The P4 row is the surprise, and it is worth stating explicitly because it is the phase that looked riskiest: **the patient-side consent flow uses no callbacks at all.** Deny (§6.21) and revoke (§6.22) are direct calls authenticated with the patient's own `X-AUTH-TOKEN`, answered `202` inline. And there is no documented push telling a PHR that a new consent request has arrived — §6.1 says requests are "broadcasted… sent to all the ABDM compliance Patient HIU (PHR application)", but no such endpoint appears anywhere in the spec's callback inventory. The mechanism the doc actually gives you is **polling** `/api/hiecm/consent/v3/request?limit&offset&status` (§6.16). See **R12**.

**So: build P0 through P4 with a single FastAPI process and no proxy, no second service registration, no ABDM-side questions.** The disambiguation decision below is real, but it is a P5 decision.

#### When you reach P5 — two options under one client ID

1. **One process, two routers (recommended).** Run a single FastAPI app that mounts both the EMR callback router and the PHR callback router behind one dispatcher and one correlation store. Route the four colliding paths by the **correlation id you generated yourself** — every one of them carries back a `requestId` or `consentRequestId` that originated on your side. Your repo already has exactly this machinery: `pending_consent_request_repository.py` with `get_pending_consent_request()` and `link_consent_request_id()`. Look the id up, see which requester owns it, dispatch. No new ABDM concepts, nothing unverified.
   *Cost:* the two backends are one process at runtime. The repos stay separate and the code stays separate — but you deploy them together. Worth deciding you're fine with that, since it is the whole basis of this option.
2. **Two processes + a header-routing proxy.** Register a second HIU-type bridge service for the PHR and route the four paths on `X-HIU-ID`. Verified that all four callbacks carry that header (§6.5, §6.6, §7.3.2). **Unverified:** whether ABDM accepts a second HIU service on a bridge that already has one, and whether it stamps the id per-service. Keeps the processes independent, at the cost of one unknown.

Option 1 needs nothing from ABDM and can be decided later with real experience. That is the reason to prefer it.

> ⚠️ There is a second, related unknown: §8.1 says *"Subscription will get auto approve for health locker"* — implying ABDM distinguishes a registered **Health Locker** from a generic HIU. Whether `SBXID_046112` carries that registration is **not confirmed** by anything I can see. Phase 6 (Subscription) is the phase most likely to be blocked by this.

### 2.2 🚩 Secrets must not start in `config.py`

Current `server/config.py` hardcodes `CLIENT_ID` and `CLIENT_SECRET`, and tracker item **M1-47 (CRITICAL)** already records a real `CLIENT_SECRET` sitting in git history. The new repo must start with `.env` + `pydantic-settings` from commit #1 — this is free to do now and expensive to retrofit.

### 2.3 Test-UI reachability

A Vercel-hosted page is served over HTTPS and cannot call `http://localhost:8000`. The PHR backend must be reachable over HTTPS (the same ngrok tunnel), and must send permissive CORS headers for the Vercel origin. Free ngrok URLs rotate on restart — make the UI's backend base URL a runtime field the user types in, not a build-time constant.

---

## 3. Feature inventory

### Block A — PHR Auth & Profile (§3) · 20 endpoints · **new code**

**Registration (3 paths → ABHA address created)**
- Register via mobile number (OTP)
- Register via ABHA number + Aadhaar OTP
- Register via ABHA number + mobile OTP
- ABHA address suggestion · availability check (`isExists`) · `enrol`

**Login (8 documented methods)**

| # | Identifier | Second factor | Scopes |
|---|---|---|---|
| 1 | Mobile number | Mobile OTP | `abha-address-login`, `mobile-verify` |
| 2 | Email ID *(optional)* | Email OTP | `abha-address-login`, `email-verify` |
| 3 | ABHA number | Aadhaar OTP | `abha-login`, `aadhaar-verify` |
| 4 | ABHA number | Mobile OTP | `abha-login`, `mobile-verify` |
| 5 | Aadhaar number | Aadhaar OTP | `abha-login`, `aadhaar-verify`, `aadhaar-otp-verify` |
| 6 | ABHA address | Password | `abha-address-login`, `password-verify` |
| 7 | ABHA address | Mobile OTP | `abha-address-login`, `mobile-verify` |
| 8 | ABHA address | Email OTP *(optional)* | `abha-address-login`, `email-verify` |

Plus `login/search` (which auth methods does this address support?) and `login/verify/user` (pick which ABHA address to sign in as, when one mobile has several).

**Profile management (14 features)**
Get profile · Update profile · Update mobile (OTP) · Update email (OTP) · Update password · Get QR code · Get PHR card · Link ABHA number via mobile OTP · Link ABHA number via Aadhaar OTP · De-link ABHA number · Switch profile · Refresh token · Logout · Get PHR public certificate

**Auth model (confirmed §3.39):** two tokens on every authenticated call —
`X-AUTH-TOKEN` = gateway session token (client-level, what you already have)
`X-token` = `Bearer <patient PHR token>` (user-level, issued at login)
Missing `X-token` → `403`. Missing `X-AUTH-TOKEN` → `401 / 900902`.

### Block B — Provider discovery + User-Initiated Linking (§10) · 15 endpoints · **new (patient side)**

- Search health facilities: `all-providers` (by state/district/name) · `provider-by-id` · `govt-programs`
- Discover → HIP searches its records by the patient's demographics
- Link init → HIP sends an OTP to the patient's registered mobile
- Link confirm → care contexts attach to the ABHA address
- 3 inbound callbacks to us: `on-discover`, `on-init`, `on-confirm` (all `/api/v3/hiu/patient/*`)

Your M2 backend already implements the HIP half of all three (`discover_service.py`, `link_init_service.py`, `link_confirm_service.py`) — this is the loop-closing block.

### Block C — Consent Manager, patient side (§6) · 19 endpoints · **new (patient side)**

- List all consent requests for the ABHA address (paginated, status filter)
- Consent request detail by ID
- **Grant** — select care contexts, HI types, date range, access mode, expiry
- **Deny** · **Revoke**
- Consent artefacts: all · by request ID · by artefact ID
- Auto-approve: set up · enable · disable (this is what makes a Health Locker work unattended)
- Get all link records for the patient (`/hip/v3/link/patient/links?limit=-1`)

### Block D — Data Flow (§7) · 5 endpoints · **mostly reuse from M3**

HIU data request · `on-request` callback · HIP/HIU notify · request status. The encryption half (`fidelius_crypto.py` — ECDH/HKDF/AES-GCM) is reused verbatim, and `health_information_hiu_push_service.py` already calls `decrypt_health_data()` end-to-end, so receiving and decrypting is largely solved. What's genuinely new is a **FHIR bundle reader** — all 17 modules in `server/fhir_builders/` write bundles; nothing turns one back into something a patient can read.

### Block E — Subscription / Health Locker (§8) · 18 endpoints · **new**

- List subscription requests · initiate · approve · deny · edit
- Categories: `LINK` (a new care context appeared) and `DATA` (new data on an existing one)
- HIU notify / on-notify pair
- Subscription detail by request ID / by subscription ID
- Patient lockers: list · detail by locker ID · **setup locker**
- Behaviour: on `LINK` → raise a consent request; on `DATA` → reuse an existing artefact and pull

### Block F — Scan & Profile Share (§5) · 4 endpoints · **new, small**

Patient scans a facility QR (`https://phrsbx.abdm.gov.in/share-profile?hipid=...&counterid=...`) → PHR pushes verified KYC to the HIP's front desk. Highest demo-value-per-line-of-code block in the whole list.

### Block G — HIP-Initiated Linking visibility (§9) · 9 endpoints · **already built, HIP side**

Nothing new to build in the PHR beyond *displaying* links the HIP created, which Block C's "get all link records" already covers.

### Block H — Gateway / session (§4) · 8 endpoints · **already built** (`server/auth.py`)

---

## 4. Flow inventory (what a user can actually do)

1. **Create an ABHA address** — 3 entry paths
2. **Sign in** — 8 methods, plus multi-address selection
3. **Manage profile** — view, edit, QR, PHR card, switch profile, logout
4. **Link an ABHA number** to the address, and de-link it
5. **Find my records** — search facility → discover → OTP → link
6. **See a consent request and decide** — grant (scoped) / deny
7. **Review and revoke** an active consent
8. **Turn on auto-approve** for a trusted locker
9. **Read my records** — pull, decrypt, render FHIR
10. **Subscribe a locker** and let it collect automatically
11. **Share my profile at a clinic counter** via QR scan
12. **See who has my data** — artefact list, link records

---

## 5. Architecture

### 5.1 Three repos

```
aegle-abdm-core/     ← NEW. Installable package. Zero ABDM-role opinions.
repo/                ← EXISTING. ABDM backend (HIP + HIU). Refactored to consume core.
aegle-phr/           ← NEW. PHR backend + test UI.
```

`aegle-abdm-core` is consumed by both via `pip install -e ../aegle-abdm-core` locally / a git URL in CI. No copy-paste, one place to fix a bug.

### 5.2 What moves into `aegle-abdm-core`

| Source (existing repo) | Target | Change needed |
|---|---|---|
| `utils.py` — `generate_request_id`, `generate_timestamp`, `call_with_retry`, `_is_transient_failure`, `generate_expiry_time`, `print_api_response` | `core/http.py` | none |
| `utils.py:get_gateway_token()` + `auth.py:generate_gateway_token()` | `core/session.py` | inject config instead of importing `server.config` |
| `crypto.py` (RSA-OAEP, cert cache + TTL + lock) | `core/rsa_crypto.py` | **parameterise the cert URL** — currently hardcodes `{ABHA_BASE_URL}/profile/public/certificate`; PHR needs `/phr/app/login/public/certificate` |
| `fidelius_crypto.py` (ECDH / HKDF / AES-GCM) | `core/fidelius.py` | none |
| `callbacks/utils/jwt_auth.py` (ABDM JWKS verification) | `core/callback_auth.py` | none |
| `callbacks/utils/flow_logger.py`, `logger.py`, `api_capture.py`, `idempotency.py`, `response.py` | `core/observability/` | none |
| `callbacks/utils/json_file_store.py` | `core/stores/jsonl.py` | keep for dev/test only |
| `fhir_builders/datetime_utils.py`, `attachment_spec.py`, `tools/dummy_emr/hi_types.py` | `core/fhir/` | none |
| **Not shared:** `config.py`, `abha.py`, `hip_linking.py`, `linking.py`, `healthinformation.py`, `fhir_builders/*` (writers) | — | HIP/M1-specific |

### 5.3 What the PHR repo adds

```
aegle-phr/
  app/
    config.py              # env-driven, no secrets in source
    main.py
    phr/                   # Block A — §3
      enrollment.py  login.py  profile.py  tokens.py
    hiecm/
      uil.py               # Block B — §10
      consent_patient.py   # Block C — §6
      dataflow.py          # Block D — §7  (adapts M3's hiu_health_information.py)
      subscription.py      # Block E — §8
      profile_share.py     # Block F — §5
      providers.py         # facility search
    callbacks/
      router.py            # /api/v3/hiu/patient/*, /api/v3/hiu/subscription-requests/*
      dispatcher.py        # same router→dispatcher→handler→service→repository shape as the existing repo
      handlers/ services/ repository/
    fhir_readers/          # NEW: bundle → display model (nothing existing does this)
    db/                    # Postgres + SQLAlchemy from day one — not .jsonl (see T-80)
  testui/                  # the Vercel app — deletable in one `rm -rf`
```

**Deliberate departure from the existing repo:** persistence is Postgres + SQLAlchemy from the start, matching the locked EMR-rebuild decisions (Aurora PostgreSQL, Mumbai, `tenant_id` + RLS). The `.jsonl` stores were a sandbox expedient; tracker item **T-80** already flags them as a standing architectural caveat. Don't inherit that debt into a repo that will hold real patient tokens.

### 5.4 Test UI — the plug-out contract

Vite + React + TS, single-page, deployed free on Vercel.

- Talks **only** to the PHR backend's own REST API. Never to ABDM directly, never to ABDM's crypto.
- Backend base URL is a **runtime input field** (survives ngrok URL rotation), persisted in `localStorage`.
- No shared types package, no codegen, no imports from the backend repo. `rm -rf testui/` and the backend is untouched.
- Every screen has a **raw request/response panel** — this is the actual point of the harness, more than the pretty screens.

**Screens:** Session/config · Register · Login (method picker) · Profile · Find records (provider search → discover → link) · Consents (list / detail / grant / deny / revoke / auto-approve) · Records (pull → decrypt → FHIR viewer) · Lockers · Scan & Share · Debug console.

---

## 6. Phase plan

Sizing is relative (S / M / L), not calendar estimates.

| Phase | Name | Size | Exit criteria |
|---|---|---|---|
| **P0** | Foundation | M | `aegle-abdm-core` extracted, existing repo refactored onto it and its test suites still pass. New PHR repo boots, `.env` config, Postgres schema, CORS, callback skeleton. Test UI deployed to Vercel and successfully calling `/health`. *No bridge/proxy work — see §2.1.* |
| **P1** | PHR Enrollment + Login | L | All 3 registration paths and all 8 login methods driven end-to-end from the Vercel UI against the real sandbox. `X-token` held and refreshed. |
| **P2** | PHR Profile | M | View/edit profile, QR, PHR card, mobile/email/password update, link + de-link ABHA number, switch profile, logout. |
| **P3** | Provider search + UIL | L | Patient discovers and links records **from your own HIP** (`IN3310002215`). First full round trip between your two repos. |
| **P4** | Consent — patient side | L | M3 HIU raises a consent → PHR lists it → patient grants → M2 HIP receives consent-notify → artefact visible in PHR. Deny and revoke both work. |
| **P5** | Data flow + FHIR reader | L | Patient pulls data on a granted consent, PHR decrypts via Fidelius, records render as readable clinical content. **First phase needing the §2.1 disambiguation decision.** |
| **P6** | Subscription / Health Locker | L | Subscription request → approve → `LINK` notification → auto consent → auto data pull. **Highest risk of a credentials blocker (§2.1).** |
| **P7** | Scan & Profile Share | S | QR URL → profile lands at the HIP. |
| **P8** | Hardening + docs | M | Signature verification (T-2), error-code taxonomy (§12, 80+ codes), token lifecycle, rate limits, Notion API Inventory entries for every new endpoint. |

**Recommended stop-and-demo point:** end of P4. That is the first moment the platform tells a complete story — a patient creates an identity, finds their records at your clinic, and controls who sees them.

---

## 7. Risks and open questions

| # | Item | Severity | Notes |
|---|---|---|---|
| R1 | 4 HIU callback paths collide between the PHR-as-locker and existing M3 code, under one shared `clientId` | 🟡 Medium — **blocks P5, not P0** | Confirmed in §4.2.4, §6.5/§6.6/§7.3.2 and in `auth.py` + `callbacks/router.py`. **Downgraded from Blocking in rev. 1:** P0–P4 need no colliding callback. Preferred fix (one process, correlation-id routing) needs nothing from ABDM. |
| R2 | Is `SBXID_046112` registered as a **Health Locker**? | 🔴 High | §8.1 implies a distinct locker registration. Unconfirmed. Blocks P6. |
| R3 | `CLIENT_SECRET` in existing git history (M1-47) | 🔴 High | Already open on the tracker. New repo must not repeat it. |
| R4 | **Face-verify login** (§2.9, §2.10) appears only as sequence diagrams — no API section in §3 | 🟡 Medium | Documented flow with no documented endpoints. Treat as out of scope until confirmed with ABDM. |
| R5 | Two base URL trees: `/phr/app/` vs `/phr/web/` (address verification) | 🟡 Medium | Spec notes both. Which calls need which is not fully spelled out. |
| R6 | FHIR **reader / renderer** does not exist | 🟡 Medium | Verified: all 17 modules in `fhir_builders/` write; the only read-side code is `tools/validate_fhir_bundles.py` (a validator, a useful starting point but not a display model). Decryption is *already* solved — `health_information_hiu_push_service.py` calls `decrypt_health_data()` today. P5's real work is bundle → readable clinical view. |
| R7 | Existing repo already contains **M3 HIU code** (commit `636177f`), but project notes say "M3 not started" | 🟡 Medium | Worth reconciling — it changes how much of Blocks C/D is reuse vs. new. |
| R8 | Spec typo `"passworrd-verify"` appears once | 🟢 Low | Use `password-verify`. Flagging so it isn't copied. |
| R9 | Endpoint `/link/patient/links/sms/notify2` (§9.3.8) — the trailing `2` | 🟢 Low | Present in both §9.3.8 and the §11 listing, so probably real, not a typo. Confirm on first call. |
| R10 | ngrok URL stability | 🟢 Low | Settled — one fixed ngrok host. Keep the test UI's backend URL a runtime field anyway; it costs nothing and survives a host change. |
| **R11** | **No documented patient "grant / approve consent request" endpoint** | 🔴 High | Verified by exhaustive search of every `URL:` line in the spec. §6.21 **deny** and §6.22 **revoke** exist; §6.13–6.15 cover an **auto-approve policy**. A manual "the patient approves this specific request" call appears nowhere, and §11's API listing omits the patient-side consent block entirely. **This is P4's central action.** Either the doc is incomplete or approval is expected to happen through auto-approve policy — needs confirmation from ABDM or a newer spec revision before P4. |
| **R12** | **No push notification to the PHR when a consent request arrives** | 🟡 Medium | §6.1 says requests are broadcast to all compliant Patient HIU / PHR apps, but no endpoint for that exists in the spec's callback inventory. Implies **polling** §6.16 (`/consent/v3/request?limit&offset&status`). Design P4 around polling; treat push as an unconfirmed bonus. |
| **R13** | M3 is missing a route the spec documents: `/api/v3/hiu/consent/request/on-status` | 🟢 Low | Present in §6.10 and in the §11 listing; absent from `server/callbacks/router.py`. Pre-existing gap in the EMR repo, not a PHR issue — flagging so it isn't inherited. |

---

## 8. Immediate next step

**P0 is unblocked — start it.** Nothing in R1 or R2 touches phases P0 through P4, so the `aegle-abdm-core` extraction can begin now. It is the one refactor that touches the existing, already-tested repo, so it wants to happen while nothing else is in flight.

Carry three questions alongside the build rather than ahead of it:

- **R11 — how does a patient actually grant a consent request?** The highest-value unknown, and the only one that could stall a planned phase (P4). Worth raising with ABDM support early, since an answer may take time to come back.
- **R2 — is `SBXID_046112` registered as a Health Locker?** Blocks P6. Testable once P0 is up.
- **R1 — one process or two at P5?** Decide with real experience during P4, not now.
