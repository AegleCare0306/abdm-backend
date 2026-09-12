"""Configuration values for ABDM APIs."""

import os
from pathlib import Path

from dotenv import load_dotenv

# P16 -- the ONE value in this file that comes from .env rather than being
# hardcoded here, deliberately: every other constant below already lives in
# git history (see aegle_phr/settings.py's own docstring calling this file
# out by name for exactly that reason), so a real credential landing here
# would repeat that mistake. DATABASE_URL isn't a secret in this sandbox
# (local docker-compose creds), but the pattern -- infra config in .env,
# not committed -- is worth establishing here rather than adding to the
# pile below. Falls back to the same value aegle_phr/.env uses (see
# server/db.py's own docstring) so a machine that hasn't created repo/.env
# yet still points at the right local database rather than failing opaquely.
#
# PATH RESOLVED RELATIVE TO THIS FILE, NOT THE PROCESS'S CWD (P17,
# 2026-09-07, real bug found live): a bare load_dotenv() searches upward
# from the current working directory, which is repo/ every time this
# codebase has been run so far -- but NOT necessarily true for every
# caller. Confirmed live: aegle_phr's own bootstrap() (Part A of P17)
# reaches into repo/'s server.config from a process whose cwd is
# aegle-phr/ (its own standalone dev server's real launch command, per
# .claude/launch.json, `cd aegle-phr && python -m aegle_phr`) -- from
# there, a bare load_dotenv() silently finds nothing, CLIENT_ID/
# CLIENT_SECRET come back None, and this file's own loud RuntimeError
# below fires -- not caught by Part A's `except ImportError`, since a
# RuntimeError isn't one, so it would have crashed that process's
# bootstrap() entirely instead of degrading gracefully the way Part A's
# comment says it should. Anchoring to this file's own directory (same
# depth-resolution convention json_file_store.py's own _STORAGE_ROOT
# already uses) makes this work regardless of the caller's cwd.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://aegle:aegle@localhost:5433/aegle_phr"
)

# Gateway Configuration
# 2026-09-07 -- moved off hardcoded values here, into .env: this file
# already leaked this exact secret into git history once by hardcoding it
# directly (see aegle_phr/settings.py's own docstring, which calls this
# file out by name for exactly that reason) -- not repeating that for
# either the existing identity or a future one. No fallback default here
# on purpose, unlike DATABASE_URL above (that one's a non-secret local
# docker-compose credential) -- a missing CLIENT_ID/CLIENT_SECRET must
# fail loudly at import, not silently reintroduce a hardcoded secret or
# limp along with a confusing failure three calls deep in
# generate_gateway_token().
CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
if not CLIENT_ID or not CLIENT_SECRET:
    raise RuntimeError(
        "CLIENT_ID and CLIENT_SECRET must be set in repo/.env -- see that file's "
        "own comment. This file no longer hardcodes them (2026-09-07)."
    )

GATEWAY_BASE_URL = "https://dev.abdm.gov.in/api/hiecm/gateway/v3"

# 2026-09-07 -- a SECOND bridge registration, believed to have PHR/HIU role
# granted (unlike CLIENT_ID/CLIENT_SECRET above -- see "HIU role not
# provisioned" in this project's own memory). From .env, NOT hardcoded like
# the pair above -- this is a fresh, still-unverified credential, not
# something to risk repeating this file's own established mistake with
# (see the DATABASE_URL comment above for that history). None until Aayush
# fills in .env; nothing in the live app reads these two -- diagnostic use
# only, until/unless the role check below actually confirms access and a
# real decision is made to use this identity for something.
PHR_CLIENT_ID = os.environ.get("PHR_CLIENT_ID") or None
PHR_CLIENT_SECRET = os.environ.get("PHR_CLIENT_SECRET") or None
ABHA_BASE_URL = "https://abhasbx.abdm.gov.in/abha/api/v3"
HIECM_BASE_URL = "https://dev.abdm.gov.in/api/hiecm"

# Facility (HFR) base URL
FACILITY_BASE_URL = "https://apihspsbx.abdm.gov.in/v4/int"

# Environment
X_CM_ID = "sbx"

# Bridge callback URL
# Current ngrok tunnel URL. Must be updated here (and re-registered via
# update_bridge_url()) whenever the tunnel restarts.
CALLBACK_URL = "https://obstruct-pasture-silver.ngrok-free.dev"

HIPS = [
    {
        "hip_id": "IN3310002215",
        "name": "Aayush Health Care"
    },
    {
        "hip_id": "IN3310002220",
        "name": "Prithvi Health Solutions"
    },
    {
        "hip_id": "IN2410002587",
        "name": "MS Hospitals"
    },
    {
        "hip_id": "IN2410002590",
        "name": "Aegle Urgent Care"
    }
]

# Shelve-not-delete override point: forces a specific ABDM HI type's FHIR
# attachment mechanism to something other than its spec-correct default
# (server/fhir_builders/attachment_spec.py's ATTACHMENT_SPEC), for a test
# run comparing mechanisms. Empty/default = always use the spec-correct
# mechanism for every HI type.
#
# Keys are HI type strings ("DiagnosticReport", "Invoice", etc. -- the
# same codes as tools/dummy_emr/hi_types.py's ALL_HI_TYPES). Values are
# the mechanism to force instead: "DocumentReference", "Binary", or
# "Media". Both builders for any HI type always stay in the codebase --
# this override is what exercises the non-default one without ever
# deleting it.
#
# Example: force DiagnosticReportRecord's Imaging sub-profile off Media
# and onto a DocumentReference-with-attachment.url-to-a-separate-Binary
# instead (the general HL7 large-file pattern), to compare against ABDM's
# Media-based guidance:
#     ATTACHMENT_STRATEGY_OVERRIDE = {"DiagnosticReport": "Binary"}
ATTACHMENT_STRATEGY_OVERRIDE = {}

# Controls whether M3 Block 2 (health information pull) fires automatically
# once a consent artefact is fetched as GRANTED, or waits for a manual
# trigger. Deliberately kept as a single override point so this can change
# without touching the trigger module's own logic. Decided 2026-08-10:
# starting as "manual" (safest for sandbox testing -- no surprise real data
# pulls). "auto" and "cache_first" are believed possible destinations but
# not yet implemented beyond a stub -- "cache_first" specifically depends
# on an unresolved question (Notion To-Do Tracker T-90: does re-pulling
# data on an already-granted consent return fresh data?) and should stay a
# no-op stub, functionally identical to "manual", until that's answered.
HEALTH_INFORMATION_TRIGGER_MODE = "manual"
