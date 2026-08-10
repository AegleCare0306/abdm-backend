"""
Document Generator.
"""

import random
from pathlib import Path

from dummy_emr.case_library import CLINICAL_CASES
from dummy_emr.master_data.diagnoses import DIAGNOSES
from dummy_emr.master_data.document_types import DOCUMENT_TYPES
from dummy_emr.utils import document_reference


# tools/dummy_emr/generators/documents.py -> parents[3] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SAMPLE_ATTACHMENTS_DIR = "tools/dummy_emr/sample_attachments"

CONTENT_TYPE_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

# case_library.py document_type -> candidate sample attachment files
# (repo-root-relative paths -- survives being run from different machines/
# working directories, matching how MASTER_OUTPUT_FOLDER/
# TRANSACTION_OUTPUT_FOLDER resolve in config.py). One is picked per row,
# deterministically, via the SAME random.seed(RANDOM_SEED)-seeded stream
# generate_dummy_emr.py's main() already seeds -- no second random source.
#
# "Diagnostic Report" has no entry: its HI type's Lab sub-profile
# (DiagnosticReportLab) has no attachment slot in the real ABDM FHIR IG, so
# these rows never carry a file. The separate "Diagnostic Report Imaging"
# rows below (Media path) are what exercise an actual Diagnostic Report
# attachment.
#
# "Wellness Record" has no entry either -- no sample file was provided in
# tools/dummy_emr/sample_attachments for it, so these rows never carry a
# file (WellnessRecord's DocumentReference slot is 0..1 optional, so this
# is a legitimate "just don't populate it" gap, not a bug).
#
# Consultation_Note_1/2/3.pdf (OPConsultRecord's own optional attachment)
# is intentionally NOT wired in here: it isn't gated by any case_library
# document_type (OPConsultation is the base type every OPD/Emergency
# encounter already has, independent of document_types), so attaching it
# would mean inventing a new, ungated selection mechanism outside what
# this generator already models -- flagged rather than guessed at.
DOCUMENT_TYPE_TO_SAMPLE_FILES = {
    "Prescription": [
        f"{_SAMPLE_ATTACHMENTS_DIR}/Prescription_1.pdf",
        f"{_SAMPLE_ATTACHMENTS_DIR}/Prescription_2.pdf",
        f"{_SAMPLE_ATTACHMENTS_DIR}/Prescription_3.pdf",
        f"{_SAMPLE_ATTACHMENTS_DIR}/Prescription_Image_1.jpg",
        f"{_SAMPLE_ATTACHMENTS_DIR}/Prescription_Image_2.jpg",
        f"{_SAMPLE_ATTACHMENTS_DIR}/Prescription_Image_3.jpg",
    ],
    "Discharge Summary": [
        f"{_SAMPLE_ATTACHMENTS_DIR}/Discharge_Summary_{i}.pdf" for i in (1, 2, 3)
    ],
    "Immunization": [
        f"{_SAMPLE_ATTACHMENTS_DIR}/Vaccination_Certificate_{i}.pdf" for i in (1, 2, 3)
    ],
    "Invoice": [
        f"{_SAMPLE_ATTACHMENTS_DIR}/Medical_Invoice_{i}.pdf" for i in (1, 2, 3)
    ],
    "Referral Note": [
        f"{_SAMPLE_ATTACHMENTS_DIR}/Referral_Letter_{i}.pdf" for i in (1, 2, 3)
    ],
}

# ~1 in 3 eligible ("Diagnostic Report" document-type) encounters also get
# an Imaging attachment -- a per-encounter deterministic coin-flip drawn
# from the same seeded stream, not a new one. There is no Imaging concept
# anywhere else in this data model (diagnostic_reports.py only generates
# Lab-style LOINC results); this is the lightweight addition described in
# this task's prompt, kept out of case_library.py entirely so it doesn't
# touch any of the 80 CLINICAL_CASES entries. See the change report for
# the fuller architectural note (DiagnosticReportImaging's real mandatory-
# media-backbone-element structure vs. this simpler bare-Media approach).
IMAGING_ATTACHMENT_PROBABILITY = 1 / 3
IMAGING_DOCUMENT_TYPE = "Diagnostic Report Imaging"


def _content_type_for(file_path):
    return CONTENT_TYPE_BY_EXTENSION.get(Path(file_path).suffix.lower(), "application/octet-stream")


def _file_size(file_path):
    return (_REPO_ROOT / file_path).stat().st_size


def _document_row(document_counter, encounter, doc_type, title, file_path=None):

    content_type = ""
    file_size_bytes = ""
    if file_path:
        content_type = _content_type_for(file_path)
        file_size_bytes = _file_size(file_path)

    return {
        "document_reference": document_reference(document_counter),
        "encounter_reference": encounter["encounter_reference"],
        "patient_reference": encounter["patient_reference"],
        "document_type": doc_type,
        "title": title,
        "status": "final",
        "authored_datetime": encounter["encounter_datetime"],
        "file_path": file_path or "",
        "content_type": content_type,
        "file_size_bytes": file_size_bytes,
    }


def generate_documents(
    encounters,
    start_index=1,
):

    documents = []

    case_lookup = {
        case["case_id"]: case
        for case in CLINICAL_CASES
    }

    diagnosis_lookup = {
        diagnosis["diagnosis_reference"]: diagnosis
        for diagnosis in DIAGNOSES
    }

    document_counter = start_index

    for encounter in encounters:

        case = case_lookup[encounter["clinical_case"]]

        if not case["document_types"]:
            continue

        diagnosis = diagnosis_lookup[case["diagnosis_reference"]]

        for doc_type in case["document_types"]:

            if doc_type not in DOCUMENT_TYPES:
                raise ValueError(
                    f"Unknown document type '{doc_type}' on case {case['case_id']}"
                )

            candidates = DOCUMENT_TYPE_TO_SAMPLE_FILES.get(doc_type)
            file_path = random.choice(candidates) if candidates else None

            documents.append(
                _document_row(
                    document_counter,
                    encounter,
                    doc_type,
                    f"{doc_type} - {diagnosis['condition_name']}",
                    file_path,
                )
            )

            document_counter += 1

            if doc_type == "Diagnostic Report" and random.random() < IMAGING_ATTACHMENT_PROBABILITY:

                variant = random.choice((1, 2, 3))

                for size_label in ("small", "large"):

                    documents.append(
                        _document_row(
                            document_counter,
                            encounter,
                            IMAGING_DOCUMENT_TYPE,
                            f"Diagnostic Imaging ({size_label}) - {diagnosis['condition_name']}",
                            f"{_SAMPLE_ATTACHMENTS_DIR}/Xray_{variant}_{size_label}.jpg",
                        )
                    )

                    document_counter += 1

    return documents
