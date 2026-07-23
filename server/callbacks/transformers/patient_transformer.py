from collections import defaultdict
import json


def build_patient_payload(records):
    """
    Converts raw patient records into the ABDM patient payload.

    Groups records by HI Type.
    """

    if not records:
        return []

    grouped_records = defaultdict(list)

    for record in records:
        grouped_records[record["hi_type"]].append(record)

    patient_payload = []

    for hi_type, hi_type_records in grouped_records.items():

        first_record = hi_type_records[0]

        patient_object = {
            "referenceNumber": first_record["patient_reference"],
            "display": first_record["name"],
            "careContexts": [],
            "hiType": hi_type,
            "count": len(hi_type_records),
        }

        for record in hi_type_records:

            patient_object["careContexts"].append(
                {
                    "referenceNumber": record["care_context_reference"],
                    "display": record["care_context_display"],
                }
            )

        patient_payload.append(patient_object)

    return patient_payload