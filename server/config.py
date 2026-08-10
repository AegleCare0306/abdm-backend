"""Configuration values for ABDM APIs."""

# Gateway Configuration
CLIENT_ID = "SBXID_046112"
CLIENT_SECRET = "42a2b6e4-59a2-45f4-9a67-0e8225038813"
GATEWAY_BASE_URL = "https://dev.abdm.gov.in/api/hiecm/gateway/v3"
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
