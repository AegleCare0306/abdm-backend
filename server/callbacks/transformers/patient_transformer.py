from collections import defaultdict
import json


def build_patient_payload(records):
    """
    Converts raw patient records into the ABDM patient payload.

    Groups records by (patient reference, HI Type).
    """

    if not records:
        return []

    # GROUPING FIX (tracker case M2-30): grouping was previously keyed by
    # `hi_type` ALONE. When one real-world patient has two different
    # hospital record numbers at the same facility (two distinct
    # `patient_reference` values -- a genuinely supported scenario, e.g.
    # merged/duplicate hospital registrations later reconciled to the
    # same ABHA address) and both records happen to share an HI Type, the
    # old code silently mislabeled the second record's care context under
    # the FIRST record's `patient_reference`/`name` (`first_record` was
    # always hi_type_records[0], picked once per hi_type group, discarding
    # every other record's own identity). Grouping by (patient_reference,
    # hi_type) instead keeps each hospital record number's care contexts
    # correctly attributed to their own referenceNumber/display, while
    # still collapsing multiple care contexts for the SAME patient
    # reference + HI Type together exactly as before (the common case is
    # unaffected).
    grouped_records = defaultdict(list)

    for record in records:
        grouped_records[(record["patient_reference"], record["hi_type"])].append(record)

    patient_payload = []

    for (patient_reference, hi_type), hi_type_records in grouped_records.items():

        first_record = hi_type_records[0]

        patient_object = {
            "referenceNumber": patient_reference,
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