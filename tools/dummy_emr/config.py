"""
Configuration for Dummy EMR Generator.
"""

from pathlib import Path

# -----------------------------------------------------------------------------
# Output Folder
# -----------------------------------------------------------------------------

BASE_OUTPUT_FOLDER = (
    Path(__file__).resolve().parents[2]
    / "server"
    / "data"
)

MASTER_OUTPUT_FOLDER = (
    BASE_OUTPUT_FOLDER
    / "master"
)

TRANSACTION_OUTPUT_FOLDER = (
    BASE_OUTPUT_FOLDER
    / "transaction"
)

BASE_OUTPUT_FOLDER.mkdir(
    parents=True,
    exist_ok=True,
)
MASTER_OUTPUT_FOLDER.mkdir(
    parents=True,
    exist_ok=True,
)
TRANSACTION_OUTPUT_FOLDER.mkdir(
    parents=True,
    exist_ok=True,
)


# -----------------------------------------------------------------------------
# Dataset Size
# -----------------------------------------------------------------------------

NUMBER_OF_DOCTORS = 10

# -----------------------------------------------------------------------------
# HIP Configuration
# -----------------------------------------------------------------------------

HIPS = [
    {
        "hip_id": "IN3310002215",
        "name": "Aayush Health Care",
        "prefix": "AHC",
        "city": "Ahmedabad",
        "state": "Gujarat",
        "organization_type": "Clinic",
        "address_line1": "Satellite Road",
        "pincode": "380015",
        "phone": "07940001001",
        "email": "contact@aayushhealthcare.in",
    },
    {
        "hip_id": "IN3310002220",
        "name": "Prithvi Health Solutions",
        "prefix": "PHS",
        "city": "Ahmedabad",
        "state": "Gujarat",
        "organization_type": "Clinic",
        "address_line1": "Prahlad Nagar",
        "pincode": "380015",
        "phone": "07940001002",
        "email": "contact@prithvihealth.in",
    },
    {
        "hip_id": "IN2410002587",
        "name": "MS Hospitals",
        "prefix": "MSH",
        "city": "Ahmedabad",
        "state": "Gujarat",
        "organization_type": "Hospital",
        "address_line1": "SG Highway",
        "pincode": "380060",
        "phone": "07940001003",
        "email": "contact@mshospitals.in",
    },
    {
        "hip_id": "IN2410002590",
        "name": "Aegle Urgent Care",
        "prefix": "AUC",
        "city": "Ahmedabad",
        "state": "Gujarat",
        "organization_type": "Urgent Care",
        "address_line1": "Satellite Road",
        "pincode": "380015",
        "phone": "07940001004",
        "email": "contact@aegleurgentcare.in",
    },
]

# -----------------------------------------------------------------------------
# Random Seed
# -----------------------------------------------------------------------------

RANDOM_SEED = 42