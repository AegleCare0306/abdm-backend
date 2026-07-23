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
):
    """
    Searches the dummy patient database.

    Priority:
        1. ABHA Address
        2. ABHA Number
        3. Mobile
        4. MR Number

    Returns:
        list: Matching patient records.
    """

    matching_records = []

    with open(CSV_FILE, newline="", encoding="utf-8") as file:

        reader = csv.DictReader(file)

        for row in reader:

            match = False

            if abha_address and row["abha_address"] == abha_address:
                match = True

            elif abha_number and row["abha_number"] == abha_number:
                match = True

            elif mobile and row["mobile"] == mobile:
                match = True

            elif mr_number and row["mr_number"] == mr_number:
                match = True

            if match:
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