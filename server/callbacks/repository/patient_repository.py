import csv
from pathlib import Path


CSV_FILE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "patient_records.csv"
)


def search_patient(
    abha_address=None,
    abha_number=None,
    mobile=None,
    mr_number=None,
    hip_id=None,
    patient_selection=None,
):
    """
    Searches the dummy patient database.

    Search Priority:
        1. ABHA Address
        2. ABHA Number
        3. Mobile
        4. MR Number

    If patient_selection is provided,
    only the selected Care Contexts are returned.

    If hip_id is provided,
    only records belonging to that facility are returned.

    Returns:
        list
    """

    matching_records = []

    # ---------------------------------------------------------
    # Selected Care Contexts (Confirm Flow)
    # ---------------------------------------------------------

    selected_contexts = set()

    if patient_selection:

        for patient in patient_selection:

            for care_context in patient.get("careContexts", []):

                selected_contexts.add(
                    care_context["referenceNumber"]
                )

    # ---------------------------------------------------------
    # Search Records
    # ---------------------------------------------------------

    with open(CSV_FILE, newline="", encoding="utf-8") as file:

        reader = csv.DictReader(file)

        for row in reader:

            # -------------------------------------------------
            # Patient Match
            # -------------------------------------------------

            patient_match = (
                (abha_address and row["abha_address"] == abha_address)
                or
                (abha_number and row["abha_number"] == abha_number)
                or
                (mobile and row["mobile"] == mobile)
                or
                (mr_number and row["mr_number"] == mr_number)
            )

            if not patient_match:
                continue

            # -------------------------------------------------
            # Facility Match
            # -------------------------------------------------

            if hip_id and row["facility_id"] != hip_id:
                continue

            # -------------------------------------------------
            # Selected Care Context Match
            # -------------------------------------------------

            if (
                selected_contexts
                and row["care_context_reference"] not in selected_contexts
            ):
                continue

            # -------------------------------------------------
            # Record
            # -------------------------------------------------

            matching_records.append(
                {
                    "patient_reference": row["patient_reference"],
                    "name": row["name"],
                    "care_context_reference": row["care_context_reference"],
                    "care_context_display": row["care_context_display"],
                    "hi_type": row["hi_type"],
                }
            )

    return matching_records