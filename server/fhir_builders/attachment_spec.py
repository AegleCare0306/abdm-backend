"""
Attachment spec-fit table.

Not runtime-measured -- this is the static "what does the real ABDM FHIR
Implementation Guide (nrces.in v6.5.0) actually say" reference table,
confirmed against the real IG and real example bundles (not derived from
this codebase). server/callbacks/utils/attachment_metrics.py's comparison
report cross-references what was actually built against this table to
answer "was this the spec-correct mechanism for this HI type" without
re-deriving it each time.

Keyed by ABDM HI type (the same 8 codes as
tools/dummy_emr/hi_types.py's ALL_HI_TYPES -- duplicated here rather than
imported, since these are fixed ABDM-defined codes, not generated data,
and this module intentionally stays a standalone server-side reference
with no tools/ dependency).

DiagnosticReport is the one HI type with two sub-kinds carrying different
attachment rules (Lab vs Imaging) -- ATTACHMENT_SPEC["DiagnosticReport"]
is a dict of sub-kind -> spec rather than a flat spec like every other
entry.
"""

ATTACHMENT_SPEC = {
    "OPConsultation": {
        "mechanism": "DocumentReference",
        "cardinality": "0..1",
        "notes": "one of 12 optional sections; current fallback/default profile",
    },
    "Prescription": {
        "mechanism": "Binary",
        "cardinality": "0..1",
        "notes": "direct entry, NOT DocumentReference -- only profile using bare Binary",
    },
    "DiagnosticReport": {
        "Lab": {
            "mechanism": None,
            "cardinality": None,
            "notes": "Lab sub-profile (DiagnosticReportLab) has no attachment slot",
        },
        "Imaging": {
            "mechanism": "Media",
            "cardinality": "1..*",
            "notes": (
                "images via Media (mandatory), optional presentedForm. Real IG: Media is referenced "
                "via a mandatory media[].link backbone element on a DiagnosticReportImaging-profiled "
                "DiagnosticReport resource, not a bare Media resource in the bundle -- this codebase's "
                "implementation is the lighter version (see server/fhir_builders/media.py docstring), "
                "flagged as a follow-up item rather than implemented in full."
            ),
        },
    },
    "DischargeSummary": {
        "mechanism": "DocumentReference",
        "cardinality": "0..1",
        "notes": "section slice",
    },
    "ImmunizationRecord": {
        "mechanism": "DocumentReference",
        "cardinality": "0..*",
        "notes": "explicitly for vaccine certificates",
    },
    "Invoice": {
        "mechanism": "DocumentReference",
        "cardinality": "disputed",
        "notes": (
            "profile description text says scanned docs attach; the one real example bundle shows "
            "none. Wired and testable, but per this project's standing rule this specific path needs "
            "a live ABDM sandbox test run (tools/m2_test_suite) before it's trusted -- not run as part "
            "of this change."
        ),
    },
    "HealthDocumentRecord": {
        "mechanism": "DocumentReference",
        "cardinality": "1..*",
        "notes": "mandatory -- this profile's entire purpose is carrying documents",
    },
    "WellnessRecord": {
        "mechanism": "DocumentReference",
        "cardinality": "0..1",
        "notes": (
            "section slice; no sample file was provided in tools/dummy_emr/sample_attachments for "
            "this HI type, so the dummy generator never populates one (see documents.py)"
        ),
    },
}


def spec_for(hi_type, sub_kind=None):
    """
    Returns the spec dict for hi_type (and, for "DiagnosticReport", the
    given sub_kind -- "Lab" or "Imaging"). Returns None if hi_type/sub_kind
    isn't recognized, rather than raising -- callers use this for
    best-effort comparison reporting, not validation.
    """
    entry = ATTACHMENT_SPEC.get(hi_type)
    if entry is None:
        return None
    if sub_kind is not None:
        return entry.get(sub_kind)
    if "mechanism" not in entry:
        # DiagnosticReport-shaped entry requested without a sub_kind.
        return None
    return entry
