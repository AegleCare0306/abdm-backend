"""
Frozen legacy data for PAT9001-PAT9004's original 12 encounters
(ENC0001-ENC0012).

These predate the encounter-ID scheme change (run-order-derived ->
identity-derived). ENC0001-ENC0005 are confirmed linked in the live ABDM
sandbox (see storage/consents.jsonl and storage/patient_link_tokens.jsonl,
both keyed by abha_address aayushchordia4611@sbx and listing careContext
references ENC0001-ENC0005). ENC0006-ENC0012 have no such confirmed
evidence in this repo's local storage/, but are frozen anyway per explicit
instruction, in case they were linked from a session/machine not reflected
in this repo's local storage/.

Every value below is copied verbatim from the current repo state
(server/data/transaction/encounters.csv) and must never be recomputed --
only ever upserted as-is whenever the owning patient is selected, so a
regeneration can never reassign these IDs to different content.

observations.py and diagnostic_reports.py draw from Python's shared global
`random` stream (seeded once in generate_dummy_emr.py's main(), never
reseeded per encounter), so the values they generate depend on how many
random draws already happened by the time a given encounter is reached --
i.e. on overall generation order, not on the encounter's own identity.
Freezing only the encounters.csv row above is therefore NOT enough to
guarantee these 12 encounters' vitals/lab-result children stay
byte-identical across a generator rewrite that changes generation order
(this one does). FROZEN_OBSERVATIONS and FROZEN_DIAGNOSTIC_REPORTS below
are copied verbatim from the current repo state
(server/data/transaction/observations.csv and diagnostic_reports.csv) as
the safe fix for that, so they can be upserted the same way instead of
ever being recomputed.

The remaining child CSVs (conditions, medication_requests, procedures,
documents, immunizations, billing) are NOT frozen here because their
generators never call `random` -- their content is a pure function of
each encounter's own clinical_case, so recomputing them for these 12
encounters would reproduce byte-identical values regardless of run order.
The new merge/upsert architecture never recomputes rows for a pre-existing
encounter_reference anyway (only brand-new encounters get run through the
generators), so this is a belt-and-suspenders snapshot for encounters.csv/
observations.csv/diagnostic_reports.csv specifically, covering the case
where those files are ever missing or rebuilt from scratch.
"""

FROZEN_ENCOUNTERS = [
    {
        "encounter_reference": "ENC0001",
        "facility_encounter_number": "AHC-2025-000001",
        "hip_id": "IN3310002215",
        "patient_reference": "PAT9001",
        "practitioner_reference": "DOC0010",
        "mr_number": "MR-AHC-000001",
        "encounter_datetime": "2025-08-08 08:54:17",
        "encounter_type": "OPD",
        "visit_reason": "Follow-up",
        "chief_complaint": "Fever for 2 days",
        "encounter_status": "finished",
        "department_reference": "DEP007",
        "clinical_case": "CASE038",
    },
    {
        "encounter_reference": "ENC0002",
        "facility_encounter_number": "AHC-2026-000002",
        "hip_id": "IN3310002215",
        "patient_reference": "PAT9001",
        "practitioner_reference": "DOC0010",
        "mr_number": "MR-AHC-000002",
        "encounter_datetime": "2026-07-01 08:54:17",
        "encounter_type": "OPD",
        "visit_reason": "Follow-up",
        "chief_complaint": "Increased thirst and frequent urination",
        "encounter_status": "finished",
        "department_reference": "DEP001",
        "clinical_case": "CASE002",
    },
    {
        "encounter_reference": "ENC0003",
        "facility_encounter_number": "PHS-2025-000001",
        "hip_id": "IN3310002220",
        "patient_reference": "PAT9001",
        "practitioner_reference": "DOC0001",
        "mr_number": "MR-PHS-000001",
        "encounter_datetime": "2025-11-30 09:54:17",
        "encounter_type": "OPD",
        "visit_reason": "Follow-up",
        "chief_complaint": "Itchy dry skin patches",
        "encounter_status": "finished",
        "department_reference": "DEP008",
        "clinical_case": "CASE043",
    },
    {
        "encounter_reference": "ENC0004",
        "facility_encounter_number": "AUC-2025-000001",
        "hip_id": "IN2410002590",
        "patient_reference": "PAT9001",
        "practitioner_reference": "DOC0003",
        "mr_number": "MR-AUC-000001",
        "encounter_datetime": "2025-12-21 04:54:17",
        "encounter_type": "OPD",
        "visit_reason": "Follow-up",
        "chief_complaint": "Ear pain and irritability",
        "encounter_status": "finished",
        "department_reference": "DEP007",
        "clinical_case": "CASE039",
    },
    {
        "encounter_reference": "ENC0005",
        "facility_encounter_number": "MSH-2024-000001",
        "hip_id": "IN2410002587",
        "patient_reference": "PAT9001",
        "practitioner_reference": "DOC0004",
        "mr_number": "MR-MSH-000001",
        "encounter_datetime": "2024-11-18 00:54:17",
        "encounter_type": "OPD",
        "visit_reason": "Follow-up",
        "chief_complaint": "Exertional chest discomfort",
        "encounter_status": "finished",
        "department_reference": "DEP002",
        "clinical_case": "CASE011",
    },
    {
        "encounter_reference": "ENC0006",
        "facility_encounter_number": "PHS-2026-000002",
        "hip_id": "IN3310002220",
        "patient_reference": "PAT9002",
        "practitioner_reference": "DOC0006",
        "mr_number": "MR-PHS-000002",
        "encounter_datetime": "2026-07-06 07:54:17",
        "encounter_type": "OPD",
        "visit_reason": "Follow-up",
        "chief_complaint": "Loose stools and vomiting since yesterday",
        "encounter_status": "finished",
        "department_reference": "DEP001",
        "clinical_case": "CASE006",
    },
    {
        "encounter_reference": "ENC0007",
        "facility_encounter_number": "AUC-2026-000002",
        "hip_id": "IN2410002590",
        "patient_reference": "PAT9002",
        "practitioner_reference": "DOC0010",
        "mr_number": "MR-AUC-000002",
        "encounter_datetime": "2026-01-10 10:54:17",
        "encounter_type": "OPD",
        "visit_reason": "Follow-up",
        "chief_complaint": "Right upper abdominal pain after meals",
        "encounter_status": "finished",
        "department_reference": "DEP014",
        "clinical_case": "CASE073",
    },
    {
        "encounter_reference": "ENC0008",
        "facility_encounter_number": "AHC-2024-000003",
        "hip_id": "IN3310002215",
        "patient_reference": "PAT9003",
        "practitioner_reference": "DOC0010",
        "mr_number": "MR-AHC-000003",
        "encounter_datetime": "2024-08-31 02:54:17",
        "encounter_type": "OPD",
        "visit_reason": "Follow-up",
        "chief_complaint": "Recurrent one-sided headache with nausea",
        "encounter_status": "finished",
        "department_reference": "DEP011",
        "clinical_case": "CASE056",
    },
    {
        "encounter_reference": "ENC0009",
        "facility_encounter_number": "AHC-2025-000004",
        "hip_id": "IN3310002215",
        "patient_reference": "PAT9003",
        "practitioner_reference": "DOC0008",
        "mr_number": "MR-AHC-000004",
        "encounter_datetime": "2025-08-11 03:54:17",
        "encounter_type": "OPD",
        "visit_reason": "Follow-up",
        "chief_complaint": "Band-like headache",
        "encounter_status": "finished",
        "department_reference": "DEP011",
        "clinical_case": "CASE057",
    },
    {
        "encounter_reference": "ENC0010",
        "facility_encounter_number": "AUC-2024-000003",
        "hip_id": "IN2410002590",
        "patient_reference": "PAT9003",
        "practitioner_reference": "DOC0006",
        "mr_number": "MR-AUC-000003",
        "encounter_datetime": "2024-10-07 06:54:17",
        "encounter_type": "OPD",
        "visit_reason": "Follow-up",
        "chief_complaint": "Fever with body ache for 3 days",
        "encounter_status": "finished",
        "department_reference": "DEP001",
        "clinical_case": "CASE003",
    },
    {
        "encounter_reference": "ENC0011",
        "facility_encounter_number": "AUC-2025-000004",
        "hip_id": "IN2410002590",
        "patient_reference": "PAT9004",
        "practitioner_reference": "DOC0010",
        "mr_number": "MR-AUC-000004",
        "encounter_datetime": "2025-07-27 01:54:17",
        "encounter_type": "OPD",
        "visit_reason": "Follow-up",
        "chief_complaint": "Loose stools and vomiting since yesterday",
        "encounter_status": "finished",
        "department_reference": "DEP001",
        "clinical_case": "CASE006",
    },
    {
        "encounter_reference": "ENC0012",
        "facility_encounter_number": "AUC-2025-000005",
        "hip_id": "IN2410002590",
        "patient_reference": "PAT9004",
        "practitioner_reference": "DOC0004",
        "mr_number": "MR-AUC-000005",
        "encounter_datetime": "2025-02-13 01:54:17",
        "encounter_type": "OPD",
        "visit_reason": "Follow-up",
        "chief_complaint": "Routine antenatal check-up",
        "encounter_status": "finished",
        "department_reference": "DEP006",
        "clinical_case": "CASE031",
    },
]


FROZEN_OBSERVATIONS = [
    {"observation_reference": "OBS0001", "encounter_reference": "ENC0001", "patient_reference": "PAT9001", "observation_master_reference": "OBS000004", "name": "Body Temperature", "loinc": "8310-5", "value": "38.7", "unit": "°C", "effective_datetime": "2025-08-08 08:54:17", "status": "final"},
    {"observation_reference": "OBS0002", "encounter_reference": "ENC0002", "patient_reference": "PAT9001", "observation_master_reference": "OBS000001", "name": "Blood Pressure", "loinc": "85354-9", "value": "117/77", "unit": "mmHg", "effective_datetime": "2026-07-01 08:54:17", "status": "final"},
    {"observation_reference": "OBS0003", "encounter_reference": "ENC0002", "patient_reference": "PAT9001", "observation_master_reference": "OBS000007", "name": "Blood Glucose", "loinc": "2339-0", "value": "162", "unit": "mg/dL", "effective_datetime": "2026-07-01 08:54:17", "status": "final"},
    {"observation_reference": "OBS0004", "encounter_reference": "ENC0004", "patient_reference": "PAT9001", "observation_master_reference": "OBS000004", "name": "Body Temperature", "loinc": "8310-5", "value": "40.0", "unit": "°C", "effective_datetime": "2025-12-21 04:54:17", "status": "final"},
    {"observation_reference": "OBS0005", "encounter_reference": "ENC0005", "patient_reference": "PAT9001", "observation_master_reference": "OBS000001", "name": "Blood Pressure", "loinc": "85354-9", "value": "161/102", "unit": "mmHg", "effective_datetime": "2024-11-18 00:54:17", "status": "final"},
    {"observation_reference": "OBS0006", "encounter_reference": "ENC0005", "patient_reference": "PAT9001", "observation_master_reference": "OBS000002", "name": "Heart Rate", "loinc": "8867-4", "value": "73", "unit": "bpm", "effective_datetime": "2024-11-18 00:54:17", "status": "final"},
    {"observation_reference": "OBS0007", "encounter_reference": "ENC0006", "patient_reference": "PAT9002", "observation_master_reference": "OBS000004", "name": "Body Temperature", "loinc": "8310-5", "value": "36.5", "unit": "°C", "effective_datetime": "2026-07-06 07:54:17", "status": "final"},
    {"observation_reference": "OBS0008", "encounter_reference": "ENC0008", "patient_reference": "PAT9003", "observation_master_reference": "OBS000001", "name": "Blood Pressure", "loinc": "85354-9", "value": "109/83", "unit": "mmHg", "effective_datetime": "2024-08-31 02:54:17", "status": "final"},
    {"observation_reference": "OBS0009", "encounter_reference": "ENC0009", "patient_reference": "PAT9003", "observation_master_reference": "OBS000001", "name": "Blood Pressure", "loinc": "85354-9", "value": "117/75", "unit": "mmHg", "effective_datetime": "2025-08-11 03:54:17", "status": "final"},
    {"observation_reference": "OBS0010", "encounter_reference": "ENC0010", "patient_reference": "PAT9003", "observation_master_reference": "OBS000004", "name": "Body Temperature", "loinc": "8310-5", "value": "39.2", "unit": "°C", "effective_datetime": "2024-10-07 06:54:17", "status": "final"},
    {"observation_reference": "OBS0011", "encounter_reference": "ENC0010", "patient_reference": "PAT9003", "observation_master_reference": "OBS000002", "name": "Heart Rate", "loinc": "8867-4", "value": "111", "unit": "bpm", "effective_datetime": "2024-10-07 06:54:17", "status": "final"},
    {"observation_reference": "OBS0012", "encounter_reference": "ENC0011", "patient_reference": "PAT9004", "observation_master_reference": "OBS000004", "name": "Body Temperature", "loinc": "8310-5", "value": "36.7", "unit": "°C", "effective_datetime": "2025-07-27 01:54:17", "status": "final"},
    {"observation_reference": "OBS0013", "encounter_reference": "ENC0012", "patient_reference": "PAT9004", "observation_master_reference": "OBS000001", "name": "Blood Pressure", "loinc": "85354-9", "value": "114/76", "unit": "mmHg", "effective_datetime": "2025-02-13 01:54:17", "status": "final"},
    {"observation_reference": "OBS0014", "encounter_reference": "ENC0012", "patient_reference": "PAT9004", "observation_master_reference": "OBS000005", "name": "Weight", "loinc": "29463-7", "value": "77.1", "unit": "kg", "effective_datetime": "2025-02-13 01:54:17", "status": "final"},
]


FROZEN_DIAGNOSTIC_REPORTS = [
    {"diagnostic_report_reference": "DRP0001", "encounter_reference": "ENC0002", "patient_reference": "PAT9001", "lab_reference": "LAB000002", "test_name": "HbA1c", "loinc": "4548-4", "category": "Diabetes", "result_value": "7.6", "reference_range": "4.0-5.6", "unit": "%", "interpretation": "High", "status": "final", "issued_datetime": "2026-07-01 08:54:17"},
    {"diagnostic_report_reference": "DRP0002", "encounter_reference": "ENC0002", "patient_reference": "PAT9001", "lab_reference": "LAB000006", "test_name": "Blood Glucose", "loinc": "2339-0", "category": "Diabetes", "result_value": "156", "reference_range": "70-110", "unit": "mg/dL", "interpretation": "High", "status": "final", "issued_datetime": "2026-07-01 08:54:17"},
    {"diagnostic_report_reference": "DRP0003", "encounter_reference": "ENC0005", "patient_reference": "PAT9001", "lab_reference": "LAB000005", "test_name": "Lipid Profile", "loinc": "24331-1", "category": "Cardiology", "result_value": "246", "reference_range": "<200", "unit": "mg/dL", "interpretation": "High", "status": "final", "issued_datetime": "2024-11-18 00:54:17"},
    {"diagnostic_report_reference": "DRP0004", "encounter_reference": "ENC0006", "patient_reference": "PAT9002", "lab_reference": "LAB000008", "test_name": "Urine Routine", "loinc": "5804-0", "category": "Urine", "result_value": "No abnormality detected", "reference_range": "No abnormality detected", "unit": "", "interpretation": "Normal", "status": "final", "issued_datetime": "2026-07-06 07:54:17"},
    {"diagnostic_report_reference": "DRP0005", "encounter_reference": "ENC0007", "patient_reference": "PAT9002", "lab_reference": "LAB000004", "test_name": "Liver Function Test", "loinc": "24325-3", "category": "Biochemistry", "result_value": "53", "reference_range": "7-40", "unit": "U/L", "interpretation": "High", "status": "final", "issued_datetime": "2026-01-10 10:54:17"},
    {"diagnostic_report_reference": "DRP0006", "encounter_reference": "ENC0010", "patient_reference": "PAT9003", "lab_reference": "LAB000001", "test_name": "Complete Blood Count", "loinc": "57021-8", "category": "Hematology", "result_value": "17797", "reference_range": "4000-11000", "unit": "cells/cumm", "interpretation": "High", "status": "final", "issued_datetime": "2024-10-07 06:54:17"},
    {"diagnostic_report_reference": "DRP0007", "encounter_reference": "ENC0011", "patient_reference": "PAT9004", "lab_reference": "LAB000008", "test_name": "Urine Routine", "loinc": "5804-0", "category": "Urine", "result_value": "No abnormality detected", "reference_range": "No abnormality detected", "unit": "", "interpretation": "Normal", "status": "final", "issued_datetime": "2025-07-27 01:54:17"},
    {"diagnostic_report_reference": "DRP0008", "encounter_reference": "ENC0012", "patient_reference": "PAT9004", "lab_reference": "LAB000001", "test_name": "Complete Blood Count", "loinc": "57021-8", "category": "Hematology", "result_value": "9040", "reference_range": "4000-11000", "unit": "cells/cumm", "interpretation": "Normal", "status": "final", "issued_datetime": "2025-02-13 01:54:17"},
    {"diagnostic_report_reference": "DRP0009", "encounter_reference": "ENC0012", "patient_reference": "PAT9004", "lab_reference": "LAB000008", "test_name": "Urine Routine", "loinc": "5804-0", "category": "Urine", "result_value": "No abnormality detected", "reference_range": "No abnormality detected", "unit": "", "interpretation": "Normal", "status": "final", "issued_datetime": "2025-02-13 01:54:17"},
]


FROZEN_ENCOUNTER_REFERENCES = {row["encounter_reference"] for row in FROZEN_ENCOUNTERS}
