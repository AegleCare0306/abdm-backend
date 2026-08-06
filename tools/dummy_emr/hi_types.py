"""
ABDM HI Type coverage rules.

Single source of truth for mapping a clinical_case's document_types +
encounter type to the ABDM HealthInformationType codes it produces. Shared
by generate_dummy_emr.py (to compute per-facility coverage gaps while
generating) and generate_patient_records.py (to compute the hi_type column
of patient_records.csv) so the two can never drift apart.

The 8 ABDM HI types are confirmed via real ABDM sandbox data -- every entry
in storage/consents.jsonl lists this exact 8-value array.
"""

ALL_HI_TYPES = frozenset(
    [
        "Prescription",
        "DiagnosticReport",
        "OPConsultation",
        "DischargeSummary",
        "ImmunizationRecord",
        "HealthDocumentRecord",
        "WellnessRecord",
        "Invoice",
    ]
)

# case_library document_types (dummy EMR's own vocabulary) -> ABDM's actual
# HealthInformationType codes.
DOCUMENT_TYPE_TO_HI_TYPE = {
    "Prescription": "Prescription",
    "Diagnostic Report": "DiagnosticReport",
    "Discharge Summary": "DischargeSummary",
    "Wellness Record": "WellnessRecord",
    "Immunization": "ImmunizationRecord",
    "Invoice": "Invoice",
    "Referral Note": "HealthDocumentRecord",
}

# encounter_type -> the base ABDM HI type every care context of that kind
# carries, regardless of which other document types it also has.
BASE_HI_TYPE_BY_ENCOUNTER_TYPE = {
    "OPD": "OPConsultation",
    "IPD": "DischargeSummary",
    "Emergency": "OPConsultation",
}


def hi_types_for_case(case):
    hi_types = {BASE_HI_TYPE_BY_ENCOUNTER_TYPE.get(case["encounter"]["type"], "OPConsultation")}
    for doc_type in case["document_types"]:
        mapped = DOCUMENT_TYPE_TO_HI_TYPE.get(doc_type)
        if mapped:
            hi_types.add(mapped)
    return hi_types
