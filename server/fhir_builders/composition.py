"""
Composition Resource Builder.
"""

from fhir.resources.R4B.composition import Composition, CompositionSection
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.meta import Meta

from server.fhir_builders.datetime_utils import to_fhir_datetime


LOINC_SYSTEM = "http://loinc.org"
SNOMED_SYSTEM = "http://snomed.info/sct"

# document_types (from case_library.py, plus "Diagnostic Report Imaging" --
# the pseudo document_type documents.py generates for the Imaging
# sub-profile, never present in case_library.py itself) -> ABDM composition
# profile + type coding. Checked in priority order (the order document_types
# appears on the case); falls back to OPConsultRecord for anything else.
#
# Where the real IG doesn't mandate a fixed SNOMED code for a profile
# (preferred, not required, binding), type_code is None and the type/section
# CodeableConcept is built text-only rather than asserting a code that isn't
# actually confirmed -- see _type_codeable_concept().
#
# Every code/URL below confirmed against the real ABDM FHIR IG (nrces.in
# v6.5.0), not guessed:
#   - Prescription record: 440545006 (PrescriptionRecord)
#   - Immunization record: 41000179103 (ImmunizationRecord)
#   - Record artifact: 419891008 (HealthDocumentRecord -- same generic
#     SNOMED concept WellnessRecord already used below; both profiles are
#     distinguished by their own meta.profile URL, not by a distinct code)
#   - DiagnosticReportRecord: no fixed code (preferred binding to a
#     "Diagnostic Report Type" value set)
#   - InvoiceRecord: fixed text "Invoice Record", no fixed code (preferred
#     binding to FHIRDocumentTypeCodes)
COMPOSITION_TYPE_BY_DOCUMENT_TYPE = {
    "Discharge Summary": (
        "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DischargeSummaryRecord",
        "373942005",
        "Discharge summary",
    ),
    "Wellness Record": (
        "https://nrces.in/ndhm/fhir/r4/StructureDefinition/WellnessRecord",
        "419891008",
        "Record artifact",
    ),
    "Prescription": (
        "https://nrces.in/ndhm/fhir/r4/StructureDefinition/PrescriptionRecord",
        "440545006",
        "Prescription record",
    ),
    "Diagnostic Report": (
        "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportRecord",
        None,
        "Diagnostic Report Record",
    ),
    "Diagnostic Report Imaging": (
        "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportRecord",
        None,
        "Diagnostic Imaging Report",
    ),
    "Immunization": (
        "https://nrces.in/ndhm/fhir/r4/StructureDefinition/ImmunizationRecord",
        "41000179103",
        "Immunization record",
    ),
    "Invoice": (
        "https://nrces.in/ndhm/fhir/r4/StructureDefinition/InvoiceRecord",
        None,
        "Invoice Record",
    ),
    "Referral Note": (
        # "Referral Note" (case_library.py's vocabulary) maps to the
        # HealthDocumentRecord HI type -- see tools/dummy_emr/hi_types.py's
        # DOCUMENT_TYPE_TO_HI_TYPE.
        "https://nrces.in/ndhm/fhir/r4/StructureDefinition/HealthDocumentRecord",
        "419891008",
        "Record artifact",
    ),
}
DEFAULT_COMPOSITION_TYPE = (
    "https://nrces.in/ndhm/fhir/r4/StructureDefinition/OPConsultRecord",
    "371530004",
    "Clinical consultation report",
)

# resource category -> (section title, LOINC/SNOMED system, code, display)
# These are standard cross-IG section codes (used in C-CDA / International
# Patient Summary too), not ABDM inventions -- safe regardless of profile.
SECTION_DEFINITIONS = {
    "condition": ("Diagnosis", LOINC_SYSTEM, "11450-4", "Problem list"),
    "medication_request": ("Medications", LOINC_SYSTEM, "10160-0", "History of medication use"),
    "observation": ("Vitals", LOINC_SYSTEM, "8716-3", "Vital signs"),
    "diagnostic_report": ("Investigations", LOINC_SYSTEM, "30954-2", "Relevant diagnostic tests/laboratory data"),
    "procedure": ("Procedures", LOINC_SYSTEM, "47519-4", "History of procedures"),
    "immunization": ("Immunizations", LOINC_SYSTEM, "11369-6", "History of immunization"),
}
CHIEF_COMPLAINT_SECTION = ("Chief Complaint", SNOMED_SYSTEM, "422843007", "Chief complaint section")

RESOURCE_TYPE_BY_CATEGORY = {
    "condition": "Condition",
    "medication_request": "MedicationRequest",
    "observation": "Observation",
    "diagnostic_report": "DiagnosticReport",
    "procedure": "Procedure",
    "immunization": "Immunization",
}


def _pick_composition_type(document_types):
    for doc_type in document_types:
        if doc_type in COMPOSITION_TYPE_BY_DOCUMENT_TYPE:
            return COMPOSITION_TYPE_BY_DOCUMENT_TYPE[doc_type]
    return DEFAULT_COMPOSITION_TYPE


def _type_codeable_concept(code, display):
    """
    Builds the CodeableConcept for a composition type/section code. When
    the real IG doesn't mandate a fixed SNOMED code for this profile
    (code is None -- preferred, not required, binding), the CodeableConcept
    is text-only rather than asserting an unconfirmed code.
    """
    if code:
        return CodeableConcept(coding=[Coding(system=SNOMED_SYSTEM, code=code, display=display)], text=display)
    return CodeableConcept(text=display)


def build_composition(
    *,
    composition_id,
    patient_id,
    encounter_id,
    practitioner_id,
    organization_id,
    composition_date,
    title,
    document_types,
    chief_complaint,
    resource_ids_by_category,
    attachment_entries=(),
):
    """
    resource_ids_by_category: dict like
        {"condition": ["CON0001"], "medication_request": ["MRQ0001", "MRQ0002"], ...}
    Only categories present as non-empty lists become sections -- an encounter
    with no medications simply has no Medications section, rather than an
    empty one.

    attachment_entries: list of {"document_type", "resource_type",
        "resource_id"} dicts, one per DocumentReference/Binary/Media
        resource built for this encounter (see
        health_information_data_service.py). Grouped by document_type into
        its own section -- one section per distinct document_type present,
        using that document_type's own COMPOSITION_TYPE_BY_DOCUMENT_TYPE
        entry as the section's code (the real IG reuses the same SNOMED
        concept for both Composition.type and Composition.section.code on
        its document-carrying profiles, e.g. ImmunizationRecord,
        HealthDocumentRecord -- confirmed, not assumed).

    NOTE (simplification, flagged): the real IG nests PrescriptionRecord's
    Binary attachment inside the SAME section as its MedicationRequest
    entries (one section, two entry slices), not a sibling section. This
    builder gives every attachment type -- including Prescription's -- its
    own sibling section instead, to keep the one-category-per-section model
    already used here for the 6 clinical categories, rather than
    generalizing entry constniction to mixed resource types within one
    section. A validator strict about section cardinality against the
    PrescriptionRecord profile specifically could flag this; revisit if
    that turns out to matter in practice.
    """

    profile, type_code, type_display = _pick_composition_type(document_types)

    sections = []

    if chief_complaint:
        title_text, system, code, display = CHIEF_COMPLAINT_SECTION
        sections.append(
            CompositionSection(
                title=title_text,
                code=CodeableConcept(coding=[Coding(system=system, code=code, display=display)]),
                text={"status": "generated", "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{chief_complaint}</div>'},
            )
        )

    for category, resource_ids in resource_ids_by_category.items():
        if not resource_ids or category not in SECTION_DEFINITIONS:
            continue
        title_text, system, code, display = SECTION_DEFINITIONS[category]
        resource_type = RESOURCE_TYPE_BY_CATEGORY[category]
        sections.append(
            CompositionSection(
                title=title_text,
                code=CodeableConcept(coding=[Coding(system=system, code=code, display=display)]),
                entry=[Reference(reference=f"{resource_type}/{rid}") for rid in resource_ids],
            )
        )

    attachments_by_document_type = {}
    attachment_order = []
    for entry in attachment_entries:
        doc_type = entry["document_type"]
        if doc_type not in attachments_by_document_type:
            attachment_order.append(doc_type)
        attachments_by_document_type.setdefault(doc_type, []).append(entry)

    for doc_type in attachment_order:
        entries = attachments_by_document_type[doc_type]
        _attachment_profile, attachment_code, attachment_display = COMPOSITION_TYPE_BY_DOCUMENT_TYPE.get(
            doc_type, (None, None, doc_type)
        )
        sections.append(
            CompositionSection(
                title=attachment_display,
                code=_type_codeable_concept(attachment_code, attachment_display),
                entry=[Reference(reference=f"{e['resource_type']}/{e['resource_id']}") for e in entries],
            )
        )

    composition = Composition(
        id=composition_id,
        meta=Meta(profile=[profile]),
        status="final",
        type=_type_codeable_concept(type_code, type_display),
        subject=Reference(reference=f"Patient/{patient_id}"),
        encounter=Reference(reference=f"Encounter/{encounter_id}"),
        date=to_fhir_datetime(composition_date),
        author=[Reference(reference=f"Practitioner/{practitioner_id}")],
        title=title,
        custodian=Reference(reference=f"Organization/{organization_id}"),
        section=sections,
    )

    return composition.model_dump(mode="json", exclude_none=True)
