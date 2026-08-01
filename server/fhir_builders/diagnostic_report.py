"""
DiagnosticReport Resource Builder.
"""

from fhir.resources.R4B.diagnosticreport import DiagnosticReport
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.meta import Meta

from server.fhir_builders.datetime_utils import to_fhir_datetime


ABDM_DIAGNOSTIC_REPORT_PROFILE = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportLab"
LOINC_SYSTEM = "http://loinc.org"

CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0074"
LAB_CATEGORY_CODE = "LAB"


def build_diagnostic_report(diagnostic_report_row):
    """
    diagnostic_report_row expected keys (matches diagnostic_reports.csv):
        diagnostic_report_reference, encounter_reference, patient_reference,
        lab_reference, test_name, loinc, category, result_value,
        reference_range, unit, interpretation, status, issued_datetime

    NOTE: the result value/reference_range/interpretation are folded into a
    human-readable conclusion string here, since diagnostic_reports.csv
    stores the result inline rather than as a linked Observation resource
    (DiagnosticReport.result normally references separate Observations --
    this is a simplification worth revisiting once real lab-system data
    produces discrete Observation resources per test).
    """

    conclusion_parts = [diagnostic_report_row["test_name"]]
    if diagnostic_report_row.get("result_value"):
        value_part = diagnostic_report_row["result_value"]
        if diagnostic_report_row.get("unit"):
            value_part += f" {diagnostic_report_row['unit']}"
        conclusion_parts.append(f"Result: {value_part}")
    if diagnostic_report_row.get("reference_range"):
        conclusion_parts.append(f"Reference range: {diagnostic_report_row['reference_range']}")
    if diagnostic_report_row.get("interpretation"):
        conclusion_parts.append(f"Interpretation: {diagnostic_report_row['interpretation']}")

    kwargs = {
        "id": diagnostic_report_row["diagnostic_report_reference"],
        "meta": Meta(profile=[ABDM_DIAGNOSTIC_REPORT_PROFILE]),
        "status": diagnostic_report_row["status"],
        "category": [
            CodeableConcept(coding=[Coding(system=CATEGORY_SYSTEM, code=LAB_CATEGORY_CODE, display="Laboratory")])
        ],
        "code": CodeableConcept(
            coding=[Coding(system=LOINC_SYSTEM, code=diagnostic_report_row["loinc"], display=diagnostic_report_row["test_name"])],
            text=diagnostic_report_row["test_name"],
        ),
        "subject": Reference(reference=f"Patient/{diagnostic_report_row['patient_reference']}"),
        "encounter": Reference(reference=f"Encounter/{diagnostic_report_row['encounter_reference']}"),
        "issued": to_fhir_datetime(diagnostic_report_row["issued_datetime"]),
        "conclusion": " | ".join(conclusion_parts),
    }

    diagnostic_report = DiagnosticReport(**kwargs)

    return diagnostic_report.model_dump(mode="json", exclude_none=True)
