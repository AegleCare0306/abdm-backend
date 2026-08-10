"""
Health Information Data Service.

Given a list of consented care context references, fetches the underlying
records and assembles one FHIR document Bundle per care context.

CURRENT DATA SOURCE: the dummy EMR CSVs under tools/dummy_emr, since
that's the only "database" that exists right now. This is the one part
of this file that will need to change once real EMR data access exists --
swap the CSV loads below for real queries (by care context / encounter
reference) and everything else stays the same, since server/fhir_builders/
was written to take plain dicts, not CSV rows specifically -- it doesn't
know or care where the dict came from.

This duplicates some of tools/generate_fhir_bundles.py's logic by design:
that script builds bundles for EVERY encounter (for testing/dev), while
this service builds bundles only for the SPECIFIC care contexts a real
consent actually covers. Worth consolidating into one shared data-access
layer once real EMR queries replace the CSV reads here -- premature to
force that abstraction now, before knowing what the real data access
pattern looks like.
"""

import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parents[3] / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from dummy_emr.config import MASTER_OUTPUT_FOLDER, TRANSACTION_OUTPUT_FOLDER
from dummy_emr.case_library import CLINICAL_CASES
from dummy_emr.hi_types import DOCUMENT_TYPE_TO_HI_TYPE

from server.fhir_builders.patient import build_patient
from server.fhir_builders.practitioner import build_practitioner
from server.fhir_builders.organization import build_organization
from server.fhir_builders.encounter import build_encounter
from server.fhir_builders.condition import build_condition
from server.fhir_builders.observation import build_observation
from server.fhir_builders.medication_request import build_medication_request
from server.fhir_builders.procedure import build_procedure
from server.fhir_builders.diagnostic_report import build_diagnostic_report
from server.fhir_builders.immunization import build_immunization
from server.fhir_builders.document_reference import build_document_reference
from server.fhir_builders.binary import build_binary
from server.fhir_builders.media import build_media
from server.fhir_builders.attachment_spec import spec_for
from server.fhir_builders.composition import build_composition
from server.fhir_builders.bundle import build_bundle
from server.callbacks.utils.attachment_metrics import record_payload_size
from server.config import ATTACHMENT_STRATEGY_OVERRIDE


def _load_csv(folder, filename):
    with open(Path(folder) / filename, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _to_fhir_instant(value):
    return value.replace(" ", "T") + "+05:30"


# ---------------------------------------------------------------------------
# Consent dateRange filtering
#
# hiRequest.dateRange arrives as two ISO 8601 UTC instants, confirmed from a
# real ABDM sandbox capture:
#     {"from": "1926-07-31T12:38:07.220Z", "to": "2026-07-31T12:38:07.220Z"}
# ("from" 100 years in the past is how the sandbox expresses "no real lower
# bound" on a broad consent grant -- so the filter has to cope with very wide
# ranges, not assume "from" is recent.)
#
# Each resource is filtered on its OWN date field rather than inheriting its
# encounter's, since a real EMR could record e.g. a lab result well after the
# visit it belongs to. Today's dummy data sets every resource's date equal to
# its encounter's, so this makes no difference to current output -- it is
# written for the real data it will eventually run against.
# ---------------------------------------------------------------------------

IST = timezone(timedelta(hours=5, minutes=30))

ENCOUNTER_DATE_FIELD = "encounter_datetime"
CONDITION_DATE_FIELD = "recorded_date"  # date-only; see _parse_row_datetime
OBSERVATION_DATE_FIELD = "effective_datetime"
MEDICATION_REQUEST_DATE_FIELD = "authored_on"
PROCEDURE_DATE_FIELD = "performed_datetime"
DIAGNOSTIC_REPORT_DATE_FIELD = "issued_datetime"
IMMUNIZATION_DATE_FIELD = "occurrence_datetime"
DOCUMENT_DATE_FIELD = "authored_datetime"

# Distinguishes "this boundary was sent but is broken" from "this boundary
# was never sent at all" -- the two must not collapse to the same outcome,
# since they call for opposite behaviour (see _is_within_date_range).
_MALFORMED = object()


def _parse_range_boundary(value):
    """
    Parses one side of hiRequest.dateRange (an ISO 8601 UTC instant, e.g.
    "2026-07-31T12:38:07.220Z").

    Three-way result:
      - None        -- boundary absent or empty, i.e. deliberately
                       open-ended on that side (ABDM's own spec allows
                       this); the caller treats it as unbounded.
      - _MALFORMED  -- boundary was sent but is not valid ISO 8601. The
                       instruction is corrupt, so the caller excludes the
                       row rather than guessing at what was intended.
      - datetime    -- successfully parsed, timezone-aware.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return _MALFORMED


def _parse_row_datetime(value):
    """
    Parses an EMR row's date field into an aware datetime.

    Two shapes occur in this data:
      - full datetime, "YYYY-MM-DD HH:MM:SS" -- encounters, observations,
        medication requests, procedures, diagnostic reports, immunizations
      - date-only, "YYYY-MM-DD" -- Condition's recorded_date

    Neither carries timezone info, so both are read as IST (+05:30): the
    same assumption to_fhir_datetime() makes and documents, since this is
    Indian hospital data.

    Returns (aware_datetime, is_date_only), or (None, False) if unparseable.
    """
    if not value:
        return None, False

    text = str(value).strip()

    try:
        if " " in text or "T" in text:
            return datetime.strptime(text.replace("T", " "), "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST), False
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=IST), True
    except ValueError:
        return None, False


def _is_within_date_range(value, date_range):
    """
    True if `value` (an EMR row's date field) falls inside `date_range`,
    inclusive on both ends.

    Passes everything when date_range is None/empty or carries neither a
    usable "from" nor "to" -- so callers that don't supply one (and any
    non-M2 code path) behave exactly as they did before date filtering
    existed. Also passes a row whose own date is missing or unparseable,
    since there is no basis to prove it out of range.

    Excludes everything when a boundary WAS sent but could not be parsed --
    see the fail-closed note below.
    """
    if not date_range:
        return True

    range_from = _parse_range_boundary(date_range.get("from"))
    range_to = _parse_range_boundary(date_range.get("to"))

    # DELIBERATE FAIL-CLOSED. A boundary that was sent but is unparseable
    # means the window we were told to honour is corrupt -- we cannot know
    # how wide it was meant to be. Excluding the row is the safe direction
    # for a filter guarding patient data: worst case we under-share and the
    # HIU re-requests, versus over-sharing records outside the consented
    # window. This is deliberately NOT the same as an absent boundary
    # (None), which is a legitimate open-ended range and stays unbounded.
    if range_from is _MALFORMED or range_to is _MALFORMED:
        return False

    if range_from is None and range_to is None:
        return True

    parsed, is_date_only = _parse_row_datetime(value)
    if parsed is None:
        return True

    if is_date_only:
        # DELIBERATE SIMPLIFICATION: Condition.recorded_date has no time
        # component, so comparing it against instant-precision boundaries
        # needs a granularity choice. Rather than inventing an arbitrary
        # time-of-day (midnight? noon?) and getting spurious edge-day
        # exclusions, the boundaries are projected onto IST calendar dates
        # and the comparison is done inclusively at day granularity. A
        # condition recorded on the same IST calendar day as either
        # boundary counts as in range.
        record_date = parsed.date()
        if range_from is not None and record_date < range_from.astimezone(IST).date():
            return False
        if range_to is not None and record_date > range_to.astimezone(IST).date():
            return False
        return True

    if range_from is not None and parsed < range_from:
        return False
    if range_to is not None and parsed > range_to:
        return False
    return True


def _rows_for_encounter(rows, encounter_reference):
    return [row for row in rows if row["encounter_reference"] == encounter_reference]


def _rows_in_range(rows, encounter_reference, date_field, date_range):
    """
    This encounter's rows, further narrowed to those whose own date field
    falls inside the consented range.
    """
    return [
        row
        for row in _rows_for_encounter(rows, encounter_reference)
        if _is_within_date_range(row.get(date_field), date_range)
    ]


# ---------------------------------------------------------------------------
# Attachment building (Part A/B/C/E of the file-attachment support task)
#
# documents.csv rows carry a file (file_path/content_type/file_size_bytes --
# see tools/dummy_emr/generators/documents.py) for every HI type that has a
# real ABDM attachment slot, except:
#   - "Diagnostic Report" (Lab sub-profile has no attachment slot at all)
#   - "Wellness Record" (no sample file was provided for it)
# "Diagnostic Report Imaging" is a pseudo document_type documents.py adds
# (never present in case_library.py) for a coin-flip subset of Diagnostic
# Report encounters, exercising the Media mechanism.
# ---------------------------------------------------------------------------

def _hi_type_and_subkind(document_type):
    """
    Maps a documents.csv row's document_type to (hi_type, sub_kind).
    sub_kind is only non-None for DiagnosticReport's two sub-profiles
    (Lab/Imaging), which carry different attachment rules -- see
    server/fhir_builders/attachment_spec.py.
    """
    if document_type == "Diagnostic Report Imaging":
        return "DiagnosticReport", "Imaging"
    if document_type == "Diagnostic Report":
        return "DiagnosticReport", "Lab"
    return DOCUMENT_TYPE_TO_HI_TYPE.get(document_type), None


def _build_attachment(document_row, patient_id, encounter_id):
    """
    Builds the FHIR resource(s) for one documents.csv row that carries a
    file, honoring ATTACHMENT_STRATEGY_OVERRIDE (server/config.py -- Part
    E's shelve-not-delete override point).

    Returns (resources, composition_entry):
      - resources: list of resource dicts to add to the bundle (usually
        one; two when an override pairs a Binary with a URL-referencing
        DocumentReference).
      - composition_entry: {"document_type", "resource_type",
        "resource_id"} for build_composition()'s attachment_entries, or
        None if this row has no file or no attachment mechanism applies
        at all (e.g. a Lab-sub-profile "Diagnostic Report" row).

    Always returns ([], None) for a row with no file_path -- callers don't
    need to check that themselves.
    """

    file_path = document_row.get("file_path")
    if not file_path:
        return [], None

    document_type = document_row["document_type"]
    hi_type, sub_kind = _hi_type_and_subkind(document_type)

    default_spec = spec_for(hi_type, sub_kind)
    default_mechanism = default_spec["mechanism"] if default_spec else None
    mechanism = ATTACHMENT_STRATEGY_OVERRIDE.get(hi_type, default_mechanism)

    if not mechanism:
        return [], None

    document_id = document_row["document_reference"]
    title = document_row["title"]
    creation = document_row["authored_datetime"]

    if mechanism == "Binary" and default_mechanism == "Binary":
        # Native Binary-attaching HI type (Prescription) -- the bare
        # Binary IS the composition section entry, no wrapping
        # DocumentReference (per the real IG: direct entry, not
        # DocumentReference).
        binary_resource = build_binary(binary_id=document_id, file_path=file_path)
        record_payload_size(binary_resource, hi_type=hi_type, mechanism="Binary", sub_kind=sub_kind, care_context_reference=encounter_id)
        return [binary_resource], {"document_type": document_type, "resource_type": "Binary", "resource_id": document_id}

    if mechanism == "Binary":
        # Override forcing a normally DocumentReference/Media-attaching HI
        # type onto the general HL7 large-file pattern (attachment.url ->
        # separate Binary resource): a bare Binary has no subject/context
        # of its own, so it can't stand in as the section entry the way
        # Prescription's native path does -- a DocumentReference whose
        # attachment.url points at the Binary becomes the section entry
        # instead.
        binary_id = f"BIN-{document_id}"
        binary_resource = build_binary(binary_id=binary_id, file_path=file_path)
        document_reference_resource = build_document_reference(
            document_id=document_id,
            patient_id=patient_id,
            encounter_id=encounter_id,
            title=title,
            creation_datetime=creation,
            attachment_url=f"Binary/{binary_id}",
        )
        record_payload_size(binary_resource, hi_type=hi_type, mechanism="Binary", sub_kind=sub_kind, care_context_reference=encounter_id)
        return (
            [binary_resource, document_reference_resource],
            {"document_type": document_type, "resource_type": "DocumentReference", "resource_id": document_id},
        )

    if mechanism == "Media":
        media_resource = build_media(
            media_id=document_id,
            patient_id=patient_id,
            encounter_id=encounter_id,
            title=title,
            creation_datetime=creation,
            file_path=file_path,
        )
        record_payload_size(media_resource, hi_type=hi_type, mechanism="Media", sub_kind=sub_kind, care_context_reference=encounter_id)
        return [media_resource], {"document_type": document_type, "resource_type": "Media", "resource_id": document_id}

    # mechanism == "DocumentReference" (the default for every other
    # attaching HI type, and also what an override targeting
    # "DocumentReference" produces directly, inline data).
    document_reference_resource = build_document_reference(
        document_id=document_id,
        patient_id=patient_id,
        encounter_id=encounter_id,
        title=title,
        creation_datetime=creation,
        file_path=file_path,
    )
    record_payload_size(document_reference_resource, hi_type=hi_type, mechanism="DocumentReference", sub_kind=sub_kind, care_context_reference=encounter_id)
    return [document_reference_resource], {"document_type": document_type, "resource_type": "DocumentReference", "resource_id": document_id}


def build_bundles_for_care_contexts(care_context_references, date_range=None):
    """
    care_context_references: list of strings, e.g. ["ENC0005", "ENC0012"].
    These map 1:1 to encounter_reference in the mock data today -- once
    real EMR data exists, a "care context" may need its own explicit
    mapping to whatever the real system's encounter/episode ID is.

    date_range: the consent's window, as ABDM sends it in
    hiRequest.dateRange -- {"from": <ISO 8601 UTC>, "to": <ISO 8601 UTC>}.
    When None or empty (the default), nothing is filtered and the result
    is exactly what it was before date filtering existed.

    Returns a dict of {care_context_reference: finished FHIR document
    Bundle dict}, containing only the care contexts a bundle was actually
    built for. Keying by reference (rather than returning a bare list)
    matters because the result can be SHORTER than the requested list, for
    two distinct reasons:

      1. no matching encounter exists at all -- a consent could in
         principle reference something no longer present, so this is
         silently skipped rather than raising; or
      2. the encounter itself falls outside date_range -- nothing in it
         could be in range, so no bundle is produced for it.

    Either way that key is simply absent from the result. A third case is
    narrower: an encounter that IS in range can still have individual
    clinical resources filtered out of its bundle by their own dates, and
    that bundle is still returned (with fewer resources in it).

    Callers must therefore pair bundles to care contexts by key, never by
    position -- positional pairing silently mis-attributes every bundle
    after the first gap.
    """

    organizations = _load_csv(MASTER_OUTPUT_FOLDER, "organizations.csv")
    practitioners = _load_csv(MASTER_OUTPUT_FOLDER, "practitioners.csv")
    patients = _load_csv(MASTER_OUTPUT_FOLDER, "patients.csv")
    encounters = _load_csv(TRANSACTION_OUTPUT_FOLDER, "encounters.csv")
    conditions = _load_csv(TRANSACTION_OUTPUT_FOLDER, "conditions.csv")
    observations = _load_csv(TRANSACTION_OUTPUT_FOLDER, "observations.csv")
    medication_requests = _load_csv(TRANSACTION_OUTPUT_FOLDER, "medication_requests.csv")
    procedures = _load_csv(TRANSACTION_OUTPUT_FOLDER, "procedures.csv")
    diagnostic_reports = _load_csv(TRANSACTION_OUTPUT_FOLDER, "diagnostic_reports.csv")
    immunizations = _load_csv(TRANSACTION_OUTPUT_FOLDER, "immunizations.csv")
    documents = _load_csv(TRANSACTION_OUTPUT_FOLDER, "documents.csv")

    case_lookup = {case["case_id"]: case for case in CLINICAL_CASES}
    organization_by_hip = {org["hip_id"]: org for org in organizations}
    practitioner_by_ref = {p["practitioner_reference"]: p for p in practitioners}
    patient_by_ref = {p["patient_reference"]: p for p in patients}
    encounter_by_ref = {e["encounter_reference"]: e for e in encounters}

    bundles = {}

    for care_context_reference in care_context_references:

        encounter_row = encounter_by_ref.get(care_context_reference)
        if encounter_row is None:
            continue

        # The encounter itself is out of the consented window -- nothing
        # inside it could be in range, so skip the whole care context.
        if not _is_within_date_range(encounter_row.get(ENCOUNTER_DATE_FIELD), date_range):
            continue

        patient_row = patient_by_ref[encounter_row["patient_reference"]]
        practitioner_row = practitioner_by_ref[encounter_row["practitioner_reference"]]
        organization_row = organization_by_hip[encounter_row["hip_id"]]
        case = case_lookup[encounter_row["clinical_case"]]

        patient_resource = build_patient(patient_row)
        practitioner_resource = build_practitioner(practitioner_row)
        organization_resource = build_organization(organization_row)
        encounter_resource = build_encounter(encounter_row)

        condition_resources = [build_condition(r) for r in _rows_in_range(conditions, care_context_reference, CONDITION_DATE_FIELD, date_range)]
        observation_resources = [build_observation(r) for r in _rows_in_range(observations, care_context_reference, OBSERVATION_DATE_FIELD, date_range)]
        medication_request_resources = [build_medication_request(r) for r in _rows_in_range(medication_requests, care_context_reference, MEDICATION_REQUEST_DATE_FIELD, date_range)]
        procedure_resources = [build_procedure(r) for r in _rows_in_range(procedures, care_context_reference, PROCEDURE_DATE_FIELD, date_range)]
        diagnostic_report_resources = [build_diagnostic_report(r) for r in _rows_in_range(diagnostic_reports, care_context_reference, DIAGNOSTIC_REPORT_DATE_FIELD, date_range)]
        immunization_resources = [build_immunization(r) for r in _rows_in_range(immunizations, care_context_reference, IMMUNIZATION_DATE_FIELD, date_range)]

        attachment_resources = []
        attachment_entries = []
        for document_row in _rows_in_range(documents, care_context_reference, DOCUMENT_DATE_FIELD, date_range):
            resources, entry = _build_attachment(document_row, patient_row["patient_reference"], care_context_reference)
            attachment_resources.extend(resources)
            if entry is not None:
                attachment_entries.append(entry)

        resource_ids_by_category = {
            "condition": [r["id"] for r in condition_resources],
            "medication_request": [r["id"] for r in medication_request_resources],
            "observation": [r["id"] for r in observation_resources],
            "diagnostic_report": [r["id"] for r in diagnostic_report_resources],
            "procedure": [r["id"] for r in procedure_resources],
            "immunization": [r["id"] for r in immunization_resources],
        }

        composition_resource = build_composition(
            composition_id=f"COMP-{care_context_reference}",
            patient_id=patient_row["patient_reference"],
            encounter_id=care_context_reference,
            practitioner_id=practitioner_row["practitioner_reference"],
            organization_id=organization_row["hip_id"],
            composition_date=encounter_row["encounter_datetime"],
            title=f"{encounter_row['visit_reason']} - {encounter_row['chief_complaint']}",
            document_types=case["document_types"],
            chief_complaint=encounter_row["chief_complaint"],
            resource_ids_by_category=resource_ids_by_category,
            attachment_entries=attachment_entries,
        )

        all_resources = (
            [patient_resource, practitioner_resource, organization_resource, encounter_resource]
            + condition_resources
            + observation_resources
            + medication_request_resources
            + procedure_resources
            + diagnostic_report_resources
            + immunization_resources
            + attachment_resources
        )

        bundle = build_bundle(
            bundle_id=f"BUNDLE-{care_context_reference}",
            composition=composition_resource,
            resources=all_resources,
            timestamp=_to_fhir_instant(encounter_row["encounter_datetime"]),
        )

        bundles[care_context_reference] = bundle

    return bundles
