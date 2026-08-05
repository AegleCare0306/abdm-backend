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
