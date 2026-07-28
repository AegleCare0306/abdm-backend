"""
Composition Resource Builder.
"""

from fhir.resources.R4B.composition import Composition, CompositionSection
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.meta import Meta


LOINC_SYSTEM = "http://loinc.org"
SNOMED_SYSTEM = "http://snomed.info/sct"

# document_types (from case_library.py) -> ABDM composition profile + type coding.
# Checked in priority order; falls back to OPConsultRecord for anything else
# (covers the common Prescription / Diagnostic Report / Referral Note cases).
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


def _pick_composition_type(document_types):
    for doc_type in document_types:
        if doc_type in COMPOSITION_TYPE_BY_DOCUMENT_TYPE:
            return COMPOSITION_TYPE_BY_DOCUMENT_TYPE[doc_type]
    return DEFAULT_COMPOSITION_TYPE


def _to_fhir_datetime(value):
    if not value:
        return None
    return value.replace(" ", "T") + "+05:30"


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
):
    """
    resource_ids_by_category: dict like
        {"condition": ["CON0001"], "medication_request": ["MRQ0001", "MRQ0002"], ...}
    Only categories present as non-empty lists become sections -- an encounter
    with no medications simply has no Medications section, rather than an
    empty one.
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
        resource_type = {
            "condition": "Condition",
            "medication_request": "MedicationRequest",
            "observation": "Observation",
            "diagnostic_report": "DiagnosticReport",
            "procedure": "Procedure",
            "immunization": "Immunization",
        }[category]
        sections.append(
            CompositionSection(
                title=title_text,
                code=CodeableConcept(coding=[Coding(system=system, code=code, display=display)]),
                entry=[Reference(reference=f"{resource_type}/{rid}") for rid in resource_ids],
            )
        )

    composition = Composition(
        id=composition_id,
        meta=Meta(profile=[profile]),
        status="final",
        type=CodeableConcept(coding=[Coding(system=SNOMED_SYSTEM, code=type_code, display=type_display)]),
        subject=Reference(reference=f"Patient/{patient_id}"),
        encounter=Reference(reference=f"Encounter/{encounter_id}"),
        date=_to_fhir_datetime(composition_date),
        author=[Reference(reference=f"Practitioner/{practitioner_id}")],
        title=title,
        custodian=Reference(reference=f"Organization/{organization_id}"),
        section=sections,
    )

    return composition.model_dump(mode="json", exclude_none=True)
