"""
Document Generator.
"""

from dummy_emr.case_library import CLINICAL_CASES
from dummy_emr.master_data.diagnoses import DIAGNOSES
from dummy_emr.master_data.document_types import DOCUMENT_TYPES
from dummy_emr.utils import document_reference


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

            documents.append(
                {
                    "document_reference": document_reference(document_counter),
                    "encounter_reference": encounter["encounter_reference"],
                    "patient_reference": encounter["patient_reference"],
                    "document_type": doc_type,
                    "title": f"{doc_type} - {diagnosis['condition_name']}",
                    "status": "final",
                    "authored_datetime": encounter["encounter_datetime"],
                }
            )

            document_counter += 1

    return documents
