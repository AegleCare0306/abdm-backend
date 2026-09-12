"""
SQLAlchemy 2.0 declarative models for repo/'s own file-backed repository
modules, moved to Postgres in three passes: P16 (the three
security-critical session stores), P17 (the remaining 9 session stores --
see that section's own banner further down this file), and the dummy EMR
pass (the 14 tables further down still -- real relational fixture data:
organizations, patients, practitioners, encounters, and every clinical
child table, replacing server/data/master/*.csv +
server/data/transaction/*.csv + server/data/patient_records.csv). Unlike
P16/P17's key-value JSONB stores, these are typed columns with real
foreign keys -- this is structured clinical data, not opaque session
blobs. `server/callbacks/utils/idempotency.py` (a cross-cutting dedup
guard, not domain data) is deliberately NOT here -- out of scope for all
three passes.

Class definitions only -- no engine, no connection, no metadata.create_all()
here. Schema changes go through Alembic (alembic/versions/), never through
create_all(); the two must not both own the schema. Mirrors aegle_phr/
models.py's own convention (same reasoning, independent copy -- see
server/db.py's own docstring for why this isn't an import from aegle_phr).

ONE TABLE PER STORE, NOT SHARED KEY-VALUE TABLES -- same reasoning
hiu_consent_repository.py's own docstring already gives for keeping the
P16 trio apart even though their shapes are identical: "merging them risks
one role's code misreading the other's data." Every table below preserves
that boundary exactly the file-backed version had it, rather than
collapsing similarly-shaped stores just because a database CAN express
them as one table with a `store` discriminator column.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for every table in this module."""


class PatientIdentity(Base):
    """
    Patient identity resolved by Discover, consumed by Link Init/Confirm --
    the Postgres-backed replacement for storage/patient_identities.jsonl
    (server/callbacks/repository/patient_identity_repository.py).
    """

    __tablename__ = "patient_identities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    abha_address: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    data: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<PatientIdentity id={self.id} abha_address={self.abha_address!r}>"


class Consent(Base):
    """
    Consent artifacts WE, as an HIP, received notification of -- the
    Postgres-backed replacement for storage/consents.jsonl
    (server/callbacks/repository/consent_repository.py). Deliberately a
    separate table from HiuConsent below even though the shape is
    identical -- see this module's own docstring.
    """

    __tablename__ = "consents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    consent_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    data: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Consent id={self.id} consent_id={self.consent_id!r}>"


class HiuConsent(Base):
    """
    Fully-fetched Consent artefacts WE, acting as an HIU, obtained via a
    real on-fetch callback for a request THIS registration itself raised
    -- the Postgres-backed replacement for storage/hiu_consents.jsonl
    (server/callbacks/repository/hiu_consent_repository.py).

    THIS IS THE TABLE THE SECURITY PROPERTY RESTS ON: a row here exists
    only because save_hiu_consent() was called from
    consent_hiu_on_fetch_service.py, in response to a genuine on-fetch
    callback for OUR OWN raised request. A consent raised through a
    different app/registration is structurally absent from this table
    regardless of what ABDM itself thinks its status is -- that's
    hiu_consent_repository.py's own get_hiu_consent()'s whole reason to
    exist, unchanged by moving its storage here.
    """

    __tablename__ = "hiu_consents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    consent_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    data: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<HiuConsent id={self.id} consent_id={self.consent_id!r}>"


# =============================================================================
# P17 -- the remaining 9 file-backed repository modules, moved off JSONL
# for the same reason as the P16 trio above (see server/callbacks/
# repository/hiu_consent_repository.py's own banner). Same "one table per
# store, never merged" rule P16 established -- kept exactly as separate as
# the files were, even where two modules share an identical shape.
# =============================================================================


class PendingCareContextLink(Base):
    """
    Postgres-backed replacement for storage/pending_care_context_links.jsonl
    (server/callbacks/repository/care_context_link_repository.py).
    """

    __tablename__ = "pending_care_context_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<PendingCareContextLink id={self.id} request_id={self.request_id!r}>"


class PendingCareContextNotify(Base):
    """
    Postgres-backed replacement for storage/pending_care_context_notifies.jsonl
    (server/callbacks/repository/care_context_notify_repository.py).
    """

    __tablename__ = "pending_care_context_notifies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<PendingCareContextNotify id={self.id} request_id={self.request_id!r}>"


class LinkSession(Base):
    """
    Postgres-backed replacement for storage/link_sessions.jsonl
    (server/callbacks/repository/link_repository.py), keyed by ABDM's own
    link_reference_number.
    """

    __tablename__ = "link_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    link_reference_number: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<LinkSession id={self.id} link_reference_number={self.link_reference_number!r}>"


class PendingLinkToken(Base):
    """
    Postgres-backed replacement for storage/pending_link_tokens.jsonl
    (server/callbacks/repository/link_token_repository.py).
    """

    __tablename__ = "pending_link_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<PendingLinkToken id={self.id} request_id={self.request_id!r}>"


class PatientLinkToken(Base):
    """
    Postgres-backed replacement for storage/patient_link_tokens.jsonl
    (server/callbacks/repository/patient_link_token_repository.py).

    `composite_key` holds the SAME "{abha_address}|{hip_id}" string the
    file-backed version used as its single key -- kept as one column on
    purpose (not split into abha_address/hip_id + a composite unique
    constraint), per P17's own scope: that split is a real improvement but
    a bigger redesign than this chunk needs. A future cleanup can
    normalize it.
    """

    __tablename__ = "patient_link_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    composite_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<PatientLinkToken id={self.id} composite_key={self.composite_key!r}>"


class PendingConsentRequest(Base):
    """
    Postgres-backed replacement for storage/pending_consent_requests.jsonl
    (server/callbacks/repository/pending_consent_request_repository.py).
    See PendingConsentRequestByConsentRequestId below for this module's own
    two-file index pattern, preserved as two tables.
    """

    __tablename__ = "pending_consent_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<PendingConsentRequest id={self.id} request_id={self.request_id!r}>"


class PendingConsentRequestByConsentRequestId(Base):
    """
    Index table: ABDM's own consentRequestId -> our REQUEST-ID. The stored
    value in the old index FILE was a bare string (the REQUEST-ID), not a
    JSON object -- `request_id` is a plain text column here, not wrapped
    in JSONB, matching that. Written together with PendingConsentRequest
    in the same transaction by link_consent_request_id() below, so the
    two tables can't drift out of sync.
    """

    __tablename__ = "pending_consent_requests_by_consent_request_id"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    consent_request_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    request_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<PendingConsentRequestByConsentRequestId id={self.id} consent_request_id={self.consent_request_id!r}>"


class PendingHealthInformationRequest(Base):
    """
    Postgres-backed replacement for
    storage/pending_health_information_requests.jsonl
    (server/callbacks/repository/pending_health_information_request_repository.py).
    See PendingHealthInformationRequestByTransactionId below for this
    module's own two-file index pattern, preserved as two tables.
    """

    __tablename__ = "pending_health_information_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<PendingHealthInformationRequest id={self.id} request_id={self.request_id!r}>"


class PendingHealthInformationRequestByTransactionId(Base):
    """
    Index table: ABDM's own transactionId -> our REQUEST-ID. Same
    reasoning as PendingConsentRequestByConsentRequestId above -- a plain
    text `request_id` column, not JSONB, matching the old index file's own
    bare-string value. Written together with PendingHealthInformationRequest
    in the same transaction by link_transaction_id() below.
    """

    __tablename__ = "pending_health_information_requests_by_transaction_id"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    request_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<PendingHealthInformationRequestByTransactionId id={self.id} transaction_id={self.transaction_id!r}>"


class HiuHealthInformation(Base):
    """
    Postgres-backed replacement for storage/hiu_health_information.jsonl
    (server/callbacks/repository/hiu_health_information_repository.py).

    NOTE ON SIZE: this file was 14.9 MB across only 118 live keys (~127 KB
    average payload -- full FHIR bundles per transaction, not small
    metadata dicts like every other store here). Postgres JSONB handles a
    payload this size with no special handling needed (TOAST storage is
    automatic) -- noted here only so nobody's surprised this table holds
    noticeably more data per row than its neighbors despite a similar row
    count.
    """

    __tablename__ = "hiu_health_information"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<HiuHealthInformation id={self.id} transaction_id={self.transaction_id!r}>"


class HealthInformationSession(Base):
    """
    Postgres-backed replacement for
    server/callbacks/repository/health_information_repository.py's own
    `_health_information_sessions` module-level dict (M2/HIP-role session
    store for the data it PUSHES out -- deliberately separate from
    HiuHealthInformation above, which is the HIU-role RECEIVED-data store;
    merging them risks one role's code misreading the other's data, same
    rule as every other pair of stores in this file).

    UNLIKE EVERY OTHER TABLE IN THIS FILE, this one replaces an IN-MEMORY
    dict, not a file -- a genuine behavior change (state now survives a
    restart and is visible across processes), not a pure storage-backend
    swap. Nothing to backfill: the dict is always empty at migration time.

    update_health_information_session() does a PARTIAL MERGE
    (`dict.update()`), not an overwrite -- the repository function against
    this table must use Postgres's JSONB `||` concat operator to match
    that shallow-merge behavior exactly, not a full replace (see that
    function's own docstring in the repository module).
    """

    __tablename__ = "health_information_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<HealthInformationSession id={self.id} transaction_id={self.transaction_id!r}>"


# =============================================================================
# Dummy EMR -- fixture clinical data, replacing server/data/master/*.csv +
# server/data/transaction/*.csv + server/data/patient_records.csv. Naive
# DateTime/Date columns throughout, matching the source CSVs' own naive
# "YYYY-MM-DD HH:MM:SS"/"YYYY-MM-DD" values exactly (no timezone stored or
# assumed here -- downstream code already treats these as local/IST,
# unchanged by this migration). String columns keep their source width
# unconstrained (Text, not VARCHAR(n)) -- this is fixture data generated by
# this project's own scripts, not user input needing a length bound.
# =============================================================================


class Organization(Base):
    """Postgres-backed replacement for server/data/master/organizations.csv."""

    __tablename__ = "organizations"

    hip_id: Mapped[str] = mapped_column(Text, primary_key=True)
    organization_name: Mapped[str] = mapped_column(Text, nullable=False)
    organization_type: Mapped[str] = mapped_column(Text, nullable=False)
    address_line1: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str | None] = mapped_column(Text, nullable=True)
    pincode: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Organization hip_id={self.hip_id!r} name={self.organization_name!r}>"


class Patient(Base):
    """
    Postgres-backed replacement for server/data/master/patients.csv.

    date_of_birth is a real DATE column here -- the source CSV stored it
    as DD-MM-YYYY text, which server/fhir_builders/patient.py's own
    build_patient() had to flip to FHIR's YYYY-MM-DD at read time. Storing
    a real date removes that flip's reason to exist (a date column
    round-trips through psycopg as a real `datetime.date`, formatted
    however the caller wants) -- the repository layer's own get_patient()
    converts back to whatever string shape a caller needs.

    abha_address/abha_number/mobile are NOT unique-constrained here even
    though each is individually meaningful for lookup -- the source data
    has two rows (two distinct patient_reference values) sharing the same
    abha_number with different abha_address (two ABHA registrations for
    the same real person), and patient_repository.py's own search_patient()
    already ORs across all of abha_address/abha_number/mobile (plus
    encounters.mr_number) rather than assuming any one of them is 1:1 --
    a unique constraint here would be a real, unrequested behavior change.
    """

    __tablename__ = "patients"

    patient_reference: Mapped[str] = mapped_column(Text, primary_key=True)
    abha_address: Mapped[str] = mapped_column(Text, nullable=False)
    abha_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    gender: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    mobile: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    blood_group: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Patient patient_reference={self.patient_reference!r} name={self.full_name!r}>"


class Practitioner(Base):
    """Postgres-backed replacement for server/data/master/practitioners.csv."""

    __tablename__ = "practitioners"

    practitioner_reference: Mapped[str] = mapped_column(Text, primary_key=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    speciality: Mapped[str | None] = mapped_column(Text, nullable=True)
    qualification: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_system: Mapped[str | None] = mapped_column(Text, nullable=True)
    mobile: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Practitioner practitioner_reference={self.practitioner_reference!r} name={self.full_name!r}>"


class PractitionerOrganization(Base):
    """
    Postgres-backed replacement for
    server/data/master/practitioner_organizations.csv -- a many-to-many
    join table between practitioners and organizations.

    `active` is a real BOOLEAN column here -- the source CSV stored it as
    the Python-str-of-a-bool "True"/"False", which tools/m3_test_suite/
    common.py's own select_practitioner() compared literally
    (`row["active"] == "True"`). The repository layer's own lookup
    function does the real boolean comparison instead.
    """

    __tablename__ = "practitioner_organizations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    practitioner_reference: Mapped[str] = mapped_column(
        Text, ForeignKey("practitioners.practitioner_reference"), nullable=False
    )
    hip_id: Mapped[str] = mapped_column(Text, ForeignKey("organizations.hip_id"), nullable=False)
    department: Mapped[str | None] = mapped_column(Text, nullable=True)
    designation: Mapped[str | None] = mapped_column(Text, nullable=True)
    joining_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    __table_args__ = (
        UniqueConstraint("practitioner_reference", "hip_id", name="uq_practitioner_organizations_practitioner_hip"),
    )

    def __repr__(self) -> str:
        return f"<PractitionerOrganization practitioner={self.practitioner_reference!r} hip_id={self.hip_id!r}>"


class Encounter(Base):
    """
    Postgres-backed replacement for server/data/transaction/encounters.csv
    -- the central fact table every clinical child table below hangs off
    of via encounter_reference.
    """

    __tablename__ = "encounters"

    encounter_reference: Mapped[str] = mapped_column(Text, primary_key=True)
    facility_encounter_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    hip_id: Mapped[str] = mapped_column(Text, ForeignKey("organizations.hip_id"), nullable=False)
    patient_reference: Mapped[str] = mapped_column(Text, ForeignKey("patients.patient_reference"), nullable=False)
    practitioner_reference: Mapped[str | None] = mapped_column(
        Text, ForeignKey("practitioners.practitioner_reference"), nullable=True
    )
    mr_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    encounter_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    encounter_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    visit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    chief_complaint: Mapped[str | None] = mapped_column(Text, nullable=True)
    encounter_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    department_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    clinical_case: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Encounter encounter_reference={self.encounter_reference!r} patient={self.patient_reference!r}>"


class Condition(Base):
    """Postgres-backed replacement for server/data/transaction/conditions.csv."""

    __tablename__ = "conditions"

    condition_reference: Mapped[str] = mapped_column(Text, primary_key=True)
    encounter_reference: Mapped[str] = mapped_column(Text, ForeignKey("encounters.encounter_reference"), nullable=False)
    patient_reference: Mapped[str] = mapped_column(Text, ForeignKey("patients.patient_reference"), nullable=False)
    clinical_case: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnosis_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    icd10_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    snomed_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    chronic: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    severity: Mapped[str | None] = mapped_column(Text, nullable=True)
    clinical_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    onset_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    recorded_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    def __repr__(self) -> str:
        return f"<Condition condition_reference={self.condition_reference!r} encounter={self.encounter_reference!r}>"


class Observation(Base):
    """
    Postgres-backed replacement for server/data/transaction/observations.csv.
    `value` stays TEXT -- polymorphic in the source data (a plain number
    for most observations, a composite "117/77"-style string for blood
    pressure), not something a single numeric column could hold correctly.
    """

    __tablename__ = "observations"

    observation_reference: Mapped[str] = mapped_column(Text, primary_key=True)
    encounter_reference: Mapped[str] = mapped_column(Text, ForeignKey("encounters.encounter_reference"), nullable=False)
    patient_reference: Mapped[str] = mapped_column(Text, ForeignKey("patients.patient_reference"), nullable=False)
    observation_master_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    loinc: Mapped[str | None] = mapped_column(Text, nullable=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Observation observation_reference={self.observation_reference!r} encounter={self.encounter_reference!r}>"


class MedicationRequest(Base):
    """
    Postgres-backed replacement for
    server/data/transaction/medication_requests.csv. `quantity` is a real
    nullable INTEGER here -- the source CSV sometimes left it a blank
    string (when `per_day` is None for certain dosage forms); NULL is the
    correct typed equivalent of that blank, not "0" or an empty string.
    """

    __tablename__ = "medication_requests"

    medication_request_reference: Mapped[str] = mapped_column(Text, primary_key=True)
    encounter_reference: Mapped[str] = mapped_column(Text, ForeignKey("encounters.encounter_reference"), nullable=False)
    patient_reference: Mapped[str] = mapped_column(Text, ForeignKey("patients.patient_reference"), nullable=False)
    medication_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    generic_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    strength: Mapped[str | None] = mapped_column(Text, nullable=True)
    atc_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    dosage_form: Mapped[str | None] = mapped_column(Text, nullable=True)
    route: Mapped[str | None] = mapped_column(Text, nullable=True)
    frequency: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    authored_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    def __repr__(self) -> str:
        return f"<MedicationRequest medication_request_reference={self.medication_request_reference!r}>"


class Procedure(Base):
    """Postgres-backed replacement for server/data/transaction/procedures.csv."""

    __tablename__ = "procedures"

    procedure_reference: Mapped[str] = mapped_column(Text, primary_key=True)
    encounter_reference: Mapped[str] = mapped_column(Text, ForeignKey("encounters.encounter_reference"), nullable=False)
    patient_reference: Mapped[str] = mapped_column(Text, ForeignKey("patients.patient_reference"), nullable=False)
    procedure_master_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    performed_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    def __repr__(self) -> str:
        return f"<Procedure procedure_reference={self.procedure_reference!r} encounter={self.encounter_reference!r}>"


class DiagnosticReport(Base):
    """
    Postgres-backed replacement for
    server/data/transaction/diagnostic_reports.csv. `result_value` stays
    TEXT -- polymorphic (numeric string, "Positive"/"Negative", or
    descriptive text for urine routine), same reasoning as
    Observation.value above.
    """

    __tablename__ = "diagnostic_reports"

    diagnostic_report_reference: Mapped[str] = mapped_column(Text, primary_key=True)
    encounter_reference: Mapped[str] = mapped_column(Text, ForeignKey("encounters.encounter_reference"), nullable=False)
    patient_reference: Mapped[str] = mapped_column(Text, ForeignKey("patients.patient_reference"), nullable=False)
    lab_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    loinc: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_range: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    interpretation: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    def __repr__(self) -> str:
        return f"<DiagnosticReport diagnostic_report_reference={self.diagnostic_report_reference!r}>"


class Immunization(Base):
    """Postgres-backed replacement for server/data/transaction/immunizations.csv."""

    __tablename__ = "immunizations"

    immunization_reference: Mapped[str] = mapped_column(Text, primary_key=True)
    encounter_reference: Mapped[str] = mapped_column(Text, ForeignKey("encounters.encounter_reference"), nullable=False)
    patient_reference: Mapped[str] = mapped_column(Text, ForeignKey("patients.patient_reference"), nullable=False)
    vaccine_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    vaccine_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurrence_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    def __repr__(self) -> str:
        return f"<Immunization immunization_reference={self.immunization_reference!r}>"


class Document(Base):
    """
    Postgres-backed replacement for server/data/transaction/documents.csv.
    file_path/content_type/file_size_bytes stay nullable -- legitimately
    blank in the source data for document types with no sample attachment
    (e.g. Wellness Record).
    """

    __tablename__ = "documents"

    document_reference: Mapped[str] = mapped_column(Text, primary_key=True)
    encounter_reference: Mapped[str] = mapped_column(Text, ForeignKey("encounters.encounter_reference"), nullable=False)
    patient_reference: Mapped[str] = mapped_column(Text, ForeignKey("patients.patient_reference"), nullable=False)
    document_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    authored_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"<Document document_reference={self.document_reference!r} type={self.document_type!r}>"


class Billing(Base):
    """
    Postgres-backed replacement for server/data/transaction/billing.csv.
    Money columns are NUMERIC(10, 2), not FLOAT -- the source data already
    rounds to 2dp and does real arithmetic (total_amount = sum of the
    other four) that a binary float could silently drift on.
    """

    __tablename__ = "billing"

    invoice_reference: Mapped[str] = mapped_column(Text, primary_key=True)
    encounter_reference: Mapped[str] = mapped_column(Text, ForeignKey("encounters.encounter_reference"), nullable=False)
    patient_reference: Mapped[str] = mapped_column(Text, ForeignKey("patients.patient_reference"), nullable=False)
    hip_id: Mapped[str] = mapped_column(Text, ForeignKey("organizations.hip_id"), nullable=False)
    consultation_fee: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    pharmacy_charge: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    investigation_charge: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    procedure_charge: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    total_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    def __repr__(self) -> str:
        return f"<Billing invoice_reference={self.invoice_reference!r} total={self.total_amount!r}>"


class PatientRecord(Base):
    """
    Postgres-backed replacement for server/data/patient_records.csv --
    denormalized (patient x encounter x hi_type) rows, one per distinct
    hi_type an encounter carries (an encounter with both OPConsultation
    and Prescription produces two rows sharing care_context_reference but
    differing hi_type -- confirmed against the source data, 287 rows
    across ~96 encounters). This is exactly what ABDM's Discovery/
    Link-Confirm flow needs (search_patient()'s own return shape) --
    kept as its own persisted, generation-time-populated table (not a
    read-time JOIN) to avoid a runtime dependency from server/ on
    tools/dummy_emr/'s own static case_library/hi_types reference data,
    and to keep this migration a faithful storage-backend swap rather
    than a behavior redesign. UNIQUE on (care_context_reference, hi_type)
    -- NOT care_context_reference alone, which would silently collapse
    an encounter's multiple hi_type rows down to just the last one
    written.
    """

    __tablename__ = "patient_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    abha_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    abha_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    mobile: Mapped[str | None] = mapped_column(Text, nullable=True)
    mr_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    facility_id: Mapped[str] = mapped_column(Text, ForeignKey("organizations.hip_id"), nullable=False)
    patient_reference: Mapped[str] = mapped_column(Text, ForeignKey("patients.patient_reference"), nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    care_context_reference: Mapped[str] = mapped_column(
        Text, ForeignKey("encounters.encounter_reference"), nullable=False
    )
    care_context_display: Mapped[str | None] = mapped_column(Text, nullable=True)
    hi_type: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("care_context_reference", "hi_type", name="uq_patient_records_care_context_hi_type"),
    )

    def __repr__(self) -> str:
        return f"<PatientRecord care_context_reference={self.care_context_reference!r} hi_type={self.hi_type!r}>"
