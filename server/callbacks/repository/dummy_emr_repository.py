"""
Repository for the dummy EMR fixture dataset -- Postgres-backed replacement
for server/data/master/*.csv, server/data/transaction/*.csv, and
server/data/patient_records.csv (organizations, patients, practitioners,
practitioner-organization links, encounters, and every clinical child
table: conditions, observations, medication_requests, procedures,
diagnostic_reports, immunizations, documents, billing, plus the
denormalized patient_records care-context-discovery table).

UNLIKE P16/P17's key-value JSONB stores, this is real relational data with
typed columns and foreign keys (see server/db_models.py's own "Dummy EMR"
section) -- but every function below still returns the SAME STRING-SHAPED
dicts csv.DictReader always produced (dates as "YYYY-MM-DD"/"YYYY-MM-DD
HH:MM:SS", booleans as "True"/"False", numbers as their string form,
missing values as "" -- never None, matching csv.DictReader's own
behaviour exactly). This is deliberate: every one of this project's 7
original CSV-reading files (server/fhir_builders/*.py,
server/callbacks/services/health_information_data_service.py,
server/hip_linking.py's own callers, tools/m2_test_suite/common.py,
tools/m3_test_suite/common.py, tools/generate_fhir_bundles.py,
tools/validate_output.py) already has its own proven parsing logic built
around that exact string shape (health_information_data_service.py's own
date-range filtering is a good example -- see its own
_parse_row_datetime()) -- keeping the shape identical means this stays a
genuine storage-backend swap, not also a silent redesign of every
consumer's own business logic. A caller that wants a real Python date/
bool/int back is free to parse the string the same way it always has.

Before this module, 7 different files read these CSVs directly (not
through one shared layer) -- this module is that shared layer now. Every
read function is a real SQL query; write functions (insert_*) are all
upserts (INSERT ... ON CONFLICT DO UPDATE), matching the generator
scripts' own prior upsert_csv()/write_csv() semantics.
"""

import re
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, Numeric, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from server.db import session_scope
from server.db_models import (
    Billing,
    Condition,
    DiagnosticReport,
    Document,
    Encounter,
    Immunization,
    MedicationRequest,
    Observation,
    Organization,
    Patient,
    PatientRecord,
    Practitioner,
    PractitionerOrganization,
    Procedure,
)


# =============================================================================
# Row -> dict serialization -- see this module's own banner for why every
# value comes back as a string (or "" for missing), matching csv.DictReader.
# =============================================================================

def _fmt(value):
    """Generic scalar -> csv.DictReader-shaped string. None -> ''."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)  # "True" / "False" -- matches str(bool) exactly, same as the old CSV data
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        # Matches the source CSVs' own float-shaped strings (e.g. "570.0"),
        # not Decimal's own str() (which can render as "570.00").
        return str(float(value))
    return str(value)


def _row_to_dict(row, columns):
    return {col: _fmt(getattr(row, col)) for col in columns}


_ORGANIZATION_COLUMNS = (
    "hip_id", "organization_name", "organization_type", "address_line1",
    "city", "state", "pincode", "phone", "email",
)
_PATIENT_COLUMNS = (
    "patient_reference", "abha_address", "abha_number", "full_name", "gender",
    "date_of_birth", "mobile", "email", "blood_group",
)
_PRACTITIONER_COLUMNS = (
    "practitioner_reference", "full_name", "speciality", "qualification",
    "registration_number", "registration_system", "mobile", "email",
)
_PRACTITIONER_ORGANIZATION_COLUMNS = (
    "practitioner_reference", "hip_id", "department", "designation", "joining_date", "active",
)
_ENCOUNTER_COLUMNS = (
    "encounter_reference", "facility_encounter_number", "hip_id", "patient_reference",
    "practitioner_reference", "mr_number", "encounter_datetime", "encounter_type",
    "visit_reason", "chief_complaint", "encounter_status", "department_reference", "clinical_case",
)
_CONDITION_COLUMNS = (
    "condition_reference", "encounter_reference", "patient_reference", "clinical_case",
    "diagnosis_reference", "condition_name", "icd10_code", "snomed_code", "chronic",
    "severity", "clinical_status", "verification_status", "onset_date", "recorded_date",
)
_OBSERVATION_COLUMNS = (
    "observation_reference", "encounter_reference", "patient_reference",
    "observation_master_reference", "name", "loinc", "value", "unit",
    "effective_datetime", "status",
)
_MEDICATION_REQUEST_COLUMNS = (
    "medication_request_reference", "encounter_reference", "patient_reference",
    "medication_reference", "generic_name", "brand_name", "strength", "atc_code",
    "dosage_form", "route", "frequency", "duration_days", "quantity", "status", "authored_on",
)
_PROCEDURE_COLUMNS = (
    "procedure_reference", "encounter_reference", "patient_reference",
    "procedure_master_reference", "name", "status", "outcome", "performed_datetime",
)
_DIAGNOSTIC_REPORT_COLUMNS = (
    "diagnostic_report_reference", "encounter_reference", "patient_reference", "lab_reference",
    "test_name", "loinc", "category", "result_value", "reference_range", "unit",
    "interpretation", "status", "issued_datetime",
)
_IMMUNIZATION_COLUMNS = (
    "immunization_reference", "encounter_reference", "patient_reference", "vaccine_reference",
    "vaccine_name", "status", "occurrence_datetime",
)
_DOCUMENT_COLUMNS = (
    "document_reference", "encounter_reference", "patient_reference", "document_type", "title",
    "status", "authored_datetime", "file_path", "content_type", "file_size_bytes",
)
_BILLING_COLUMNS = (
    "invoice_reference", "encounter_reference", "patient_reference", "hip_id",
    "consultation_fee", "pharmacy_charge", "investigation_charge", "procedure_charge",
    "total_amount", "currency", "status", "invoice_date",
)
_PATIENT_RECORD_COLUMNS = (
    "abha_address", "abha_number", "mobile", "mr_number", "facility_id", "patient_reference",
    "name", "care_context_reference", "care_context_display", "hi_type",
)


_TYPED_COLUMN_TYPES = (Date, DateTime, Integer, BigInteger, Numeric)


def _coerce_value(col_type, value):
    """
    The dummy EMR generators (tools/dummy_emr/generators/*.py) are pure
    functions that still produce CSV-writer-shaped values -- dates/
    datetimes as "YYYY-MM-DD"/"YYYY-MM-DD HH:MM:SS" strings (usually
    sliced or copied straight from an encounter's own encounter_datetime
    string), numbers as either a real int or "" when blank (e.g.
    medication_requests.py's own quantity, documents.py's own
    file_size_bytes) -- unchanged by this migration (see this module's
    own docstring for why: keeping generator output shape identical to
    the CSV era means this migration stays a pure storage-backend swap).
    This is the one place that bridges that string shape to the real
    typed columns db_models.py declares, driven by the column's own
    declared type so every insert_*() function above gets this for free
    instead of the orchestrator (tools/generate_dummy_emr.py) having to
    hand-convert each date/datetime/numeric field itself.
    """
    if isinstance(value, str) and value == "" and isinstance(col_type, _TYPED_COLUMN_TYPES):
        return None
    if isinstance(value, str):
        if isinstance(col_type, DateTime):
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        if isinstance(col_type, Date):
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        if isinstance(col_type, (Integer, BigInteger)):
            return int(value)
        if isinstance(col_type, Numeric):
            return Decimal(value)
        if isinstance(col_type, Boolean):
            return value == "True"
    return value


def _upsert(session, model, pk_columns, data):
    table_columns = model.__table__.columns
    coerced = {k: _coerce_value(table_columns[k].type, v) for k, v in data.items()}
    stmt = pg_insert(model).values(**coerced)
    update_cols = {k: stmt.excluded[k] for k in coerced if k not in pk_columns}
    if update_cols:
        stmt = stmt.on_conflict_do_update(index_elements=list(pk_columns), set_=update_cols)
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=list(pk_columns))
    session.execute(stmt)


def next_reference_index(model, ref_column, prefix):
    """
    DB-backed equivalent of tools/dummy_emr/csv_writer.py's own
    next_reference_index(): one past the highest N found in this table's
    `ref_column` among values matching "{prefix}{N}" (e.g. prefix="OBS"
    matches "OBS0001" -> 1), or 1 if none match. Used by the dummy EMR
    generator orchestrator (tools/generate_dummy_emr.py) so a brand-new
    row's own reference ID always continues forward from whatever is
    already in Postgres, exactly like the old CSV-scanning version did
    for the file it read.
    """
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    column = getattr(model, ref_column)

    with session_scope() as session:
        values = [v for (v,) in session.query(column).filter(column.like(f"{prefix}%")).all()]

    best = 0
    for value in values:
        match = pattern.match(value)
        if match:
            best = max(best, int(match.group(1)))
    return best + 1


# =============================================================================
# Organizations
# =============================================================================

def get_organization(hip_id):
    with session_scope() as session:
        row = session.query(Organization).filter(Organization.hip_id == hip_id).one_or_none()
        return _row_to_dict(row, _ORGANIZATION_COLUMNS) if row is not None else None


def get_all_organizations():
    with session_scope() as session:
        return [_row_to_dict(row, _ORGANIZATION_COLUMNS) for row in session.query(Organization).all()]


def insert_organization(data):
    """Upsert, keyed by hip_id. `data` matches organizations.csv's own column set."""
    with session_scope() as session:
        _upsert(session, Organization, ("hip_id",), data)


# =============================================================================
# Patients
# =============================================================================

def get_patient(patient_reference):
    with session_scope() as session:
        row = session.query(Patient).filter(Patient.patient_reference == patient_reference).one_or_none()
        return _row_to_dict(row, _PATIENT_COLUMNS) if row is not None else None


def get_all_patients():
    with session_scope() as session:
        return [_row_to_dict(row, _PATIENT_COLUMNS) for row in session.query(Patient).all()]


def insert_patient(data):
    """
    Upsert, keyed by patient_reference. `data["date_of_birth"]`, if
    present, must be a real `datetime.date` (or None) -- the generator's
    own call site is responsible for parsing whatever source format it
    has (the old CSV stored DD-MM-YYYY) before calling this.
    """
    with session_scope() as session:
        _upsert(session, Patient, ("patient_reference",), data)


# =============================================================================
# Practitioners
# =============================================================================

def get_practitioner(practitioner_reference):
    with session_scope() as session:
        row = (
            session.query(Practitioner)
            .filter(Practitioner.practitioner_reference == practitioner_reference)
            .one_or_none()
        )
        return _row_to_dict(row, _PRACTITIONER_COLUMNS) if row is not None else None


def get_all_practitioners():
    with session_scope() as session:
        return [_row_to_dict(row, _PRACTITIONER_COLUMNS) for row in session.query(Practitioner).all()]


def insert_practitioner(data):
    """Upsert, keyed by practitioner_reference."""
    with session_scope() as session:
        _upsert(session, Practitioner, ("practitioner_reference",), data)


# =============================================================================
# Practitioner <-> Organization links
# =============================================================================

def get_practitioner_organizations(hip_id=None, active_only=False):
    """
    Returns [{practitioner_reference, hip_id, department, designation,
    joining_date, active}, ...], each merged with that practitioner's own
    full_name/speciality/registration_number/registration_system (the
    exact join tools/m3_test_suite/common.py's own select_practitioner()
    already does by hand) -- filtered by hip_id when given, and by a REAL
    boolean `active` column when active_only=True (replacing the old
    `row["active"] == "True"` string comparison call sites had to do
    themselves against the file-backed data).
    """
    with session_scope() as session:
        query = (
            session.query(PractitionerOrganization, Practitioner)
            .join(Practitioner, Practitioner.practitioner_reference == PractitionerOrganization.practitioner_reference)
        )
        if hip_id is not None:
            query = query.filter(PractitionerOrganization.hip_id == hip_id)
        if active_only:
            query = query.filter(PractitionerOrganization.active.is_(True))

        results = []
        for link, practitioner in query.all():
            row = _row_to_dict(link, _PRACTITIONER_ORGANIZATION_COLUMNS)
            row["full_name"] = practitioner.full_name or ""
            row["speciality"] = practitioner.speciality or ""
            row["registration_number"] = practitioner.registration_number or ""
            row["registration_system"] = practitioner.registration_system or ""
            results.append(row)
        return results


def insert_practitioner_organization(data):
    """Upsert, keyed by (practitioner_reference, hip_id)."""
    with session_scope() as session:
        _upsert(session, PractitionerOrganization, ("practitioner_reference", "hip_id"), data)


# =============================================================================
# Encounters
# =============================================================================

def get_encounter(encounter_reference):
    with session_scope() as session:
        row = session.query(Encounter).filter(Encounter.encounter_reference == encounter_reference).one_or_none()
        return _row_to_dict(row, _ENCOUNTER_COLUMNS) if row is not None else None


def get_all_encounters():
    with session_scope() as session:
        return [_row_to_dict(row, _ENCOUNTER_COLUMNS) for row in session.query(Encounter).all()]


def get_encounters_for_patient(patient_reference):
    with session_scope() as session:
        rows = session.query(Encounter).filter(Encounter.patient_reference == patient_reference).all()
        return [_row_to_dict(row, _ENCOUNTER_COLUMNS) for row in rows]


def get_encounters_for_hip(hip_id):
    with session_scope() as session:
        rows = session.query(Encounter).filter(Encounter.hip_id == hip_id).all()
        return [_row_to_dict(row, _ENCOUNTER_COLUMNS) for row in rows]


def insert_encounter(data):
    """
    Upsert, keyed by encounter_reference. `data["encounter_datetime"]`, if
    present, must be a real `datetime.datetime` (or None).
    """
    with session_scope() as session:
        _upsert(session, Encounter, ("encounter_reference",), data)


# =============================================================================
# Clinical child tables -- one get_all_*() + one get_*_for_encounter() +
# one insert_*() per table, same shape throughout.
# =============================================================================

def get_all_conditions():
    with session_scope() as session:
        return [_row_to_dict(row, _CONDITION_COLUMNS) for row in session.query(Condition).all()]


def get_conditions_for_encounter(encounter_reference):
    with session_scope() as session:
        rows = session.query(Condition).filter(Condition.encounter_reference == encounter_reference).all()
        return [_row_to_dict(row, _CONDITION_COLUMNS) for row in rows]


def insert_condition(data):
    with session_scope() as session:
        _upsert(session, Condition, ("condition_reference",), data)


def get_all_observations():
    with session_scope() as session:
        return [_row_to_dict(row, _OBSERVATION_COLUMNS) for row in session.query(Observation).all()]


def get_observations_for_encounter(encounter_reference):
    with session_scope() as session:
        rows = session.query(Observation).filter(Observation.encounter_reference == encounter_reference).all()
        return [_row_to_dict(row, _OBSERVATION_COLUMNS) for row in rows]


def insert_observation(data):
    with session_scope() as session:
        _upsert(session, Observation, ("observation_reference",), data)


def get_all_medication_requests():
    with session_scope() as session:
        return [_row_to_dict(row, _MEDICATION_REQUEST_COLUMNS) for row in session.query(MedicationRequest).all()]


def get_medication_requests_for_encounter(encounter_reference):
    with session_scope() as session:
        rows = (
            session.query(MedicationRequest)
            .filter(MedicationRequest.encounter_reference == encounter_reference)
            .all()
        )
        return [_row_to_dict(row, _MEDICATION_REQUEST_COLUMNS) for row in rows]


def insert_medication_request(data):
    with session_scope() as session:
        _upsert(session, MedicationRequest, ("medication_request_reference",), data)


def get_all_procedures():
    with session_scope() as session:
        return [_row_to_dict(row, _PROCEDURE_COLUMNS) for row in session.query(Procedure).all()]


def get_procedures_for_encounter(encounter_reference):
    with session_scope() as session:
        rows = session.query(Procedure).filter(Procedure.encounter_reference == encounter_reference).all()
        return [_row_to_dict(row, _PROCEDURE_COLUMNS) for row in rows]


def insert_procedure(data):
    with session_scope() as session:
        _upsert(session, Procedure, ("procedure_reference",), data)


def get_all_diagnostic_reports():
    with session_scope() as session:
        return [_row_to_dict(row, _DIAGNOSTIC_REPORT_COLUMNS) for row in session.query(DiagnosticReport).all()]


def get_diagnostic_reports_for_encounter(encounter_reference):
    with session_scope() as session:
        rows = (
            session.query(DiagnosticReport)
            .filter(DiagnosticReport.encounter_reference == encounter_reference)
            .all()
        )
        return [_row_to_dict(row, _DIAGNOSTIC_REPORT_COLUMNS) for row in rows]


def insert_diagnostic_report(data):
    with session_scope() as session:
        _upsert(session, DiagnosticReport, ("diagnostic_report_reference",), data)


def get_all_immunizations():
    with session_scope() as session:
        return [_row_to_dict(row, _IMMUNIZATION_COLUMNS) for row in session.query(Immunization).all()]


def get_immunizations_for_encounter(encounter_reference):
    with session_scope() as session:
        rows = session.query(Immunization).filter(Immunization.encounter_reference == encounter_reference).all()
        return [_row_to_dict(row, _IMMUNIZATION_COLUMNS) for row in rows]


def insert_immunization(data):
    with session_scope() as session:
        _upsert(session, Immunization, ("immunization_reference",), data)


def get_all_documents():
    with session_scope() as session:
        return [_row_to_dict(row, _DOCUMENT_COLUMNS) for row in session.query(Document).all()]


def get_documents_for_encounter(encounter_reference):
    with session_scope() as session:
        rows = session.query(Document).filter(Document.encounter_reference == encounter_reference).all()
        return [_row_to_dict(row, _DOCUMENT_COLUMNS) for row in rows]


def insert_document(data):
    with session_scope() as session:
        _upsert(session, Document, ("document_reference",), data)


def get_all_billing():
    with session_scope() as session:
        return [_row_to_dict(row, _BILLING_COLUMNS) for row in session.query(Billing).all()]


def get_billing_for_encounter(encounter_reference):
    with session_scope() as session:
        rows = session.query(Billing).filter(Billing.encounter_reference == encounter_reference).all()
        return [_row_to_dict(row, _BILLING_COLUMNS) for row in rows]


def insert_billing(data):
    with session_scope() as session:
        _upsert(session, Billing, ("invoice_reference",), data)


# =============================================================================
# Patient records -- the denormalized (patient x encounter x hi_type) care-
# context-discovery table, replacing server/data/patient_records.csv +
# tools/generate_patient_records.py. Populated at encounter-generation time
# (see this module's own docstring / server/db_models.py:PatientRecord's
# own docstring for why this stays a persisted table, not a read-time
# JOIN) -- generate_patient_records() below is what
# tools/generate_dummy_emr.py's own pipeline now calls per new encounter,
# in place of the old separate tools/generate_patient_records.py script.
# =============================================================================

def insert_patient_record(data):
    """Upsert, keyed by (care_context_reference, hi_type) -- NOT care_context_reference alone, see PatientRecord's own docstring."""
    with session_scope() as session:
        _upsert(session, PatientRecord, ("care_context_reference", "hi_type"), data)


def search_patient(
    abha_address=None,
    abha_number=None,
    mobile=None,
    mr_number=None,
    hip_id=None,
    patient_selection=None,
):
    """
    Postgres-backed replacement for patient_repository.py's own
    search_patient() -- SAME signature, SAME OR-across-4-fields match
    contract (a row matches if ANY of abha_address/abha_number/mobile/
    mr_number equals the corresponding column), SAME optional hip_id and
    patient_selection narrowing, SAME return shape (a list of
    {patient_reference, name, care_context_reference, care_context_display,
    hi_type} dicts).

    `patient_selection`, when given, is a LIST of patient dicts (each
    carrying its own "careContexts" list of {"referenceNumber": ...}
    entries) -- the on-confirm session's own selected_patient_records
    shape, matching patient_repository.py's original nested loop exactly.
    """
    if not any([abha_address, abha_number, mobile, mr_number]):
        return []

    with session_scope() as session:
        query = session.query(PatientRecord)
        conditions = []
        if abha_address:
            conditions.append(PatientRecord.abha_address == abha_address)
        if abha_number:
            conditions.append(PatientRecord.abha_number == abha_number)
        if mobile:
            conditions.append(PatientRecord.mobile == mobile)
        if mr_number:
            conditions.append(PatientRecord.mr_number == mr_number)

        query = query.filter(or_(*conditions))
        if hip_id:
            query = query.filter(PatientRecord.facility_id == hip_id)

        rows = query.all()

        results = [
            {
                "patient_reference": row.patient_reference,
                "name": row.name or "",
                "care_context_reference": row.care_context_reference,
                "care_context_display": row.care_context_display or "",
                "hi_type": row.hi_type,
            }
            for row in rows
        ]

    if patient_selection:
        selected_contexts = {
            care_context["referenceNumber"]
            for patient in patient_selection
            for care_context in patient.get("careContexts", [])
        }
        if selected_contexts:
            results = [r for r in results if r["care_context_reference"] in selected_contexts]

    return results
