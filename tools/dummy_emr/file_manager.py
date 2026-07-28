"""
File Management Utilities.
"""

from pathlib import Path

from dummy_emr.config import BASE_OUTPUT_FOLDER
from dummy_emr.config import MASTER_OUTPUT_FOLDER
from dummy_emr.config import TRANSACTION_OUTPUT_FOLDER


def create_output_folders():
    """
    Creates output folders if they do not exist.
    """

    MASTER_OUTPUT_FOLDER.mkdir(
        parents=True,
        exist_ok=True,
    )

    TRANSACTION_OUTPUT_FOLDER.mkdir(
        parents=True,
        exist_ok=True,
    )


def clear_output_folder():
    """
    Deletes generated transaction CSVs only.

    Master data (organizations, practitioners, practitioner_organizations,
    patients) is treated as a persistent directory/identity layer, not
    disposable per-run output, so it is left untouched here. It is still
    rewritten in place by write_csv() on every run (which always overwrites
    rather than appends), so it stays in sync with config.py and the fixed
    patient list in patients.py — it just isn't blown away by clear step,
    which matters if it's ever hand-edited between runs.
    """

    create_output_folders()

    deleted = 0

    for file in TRANSACTION_OUTPUT_FOLDER.rglob("*.csv"):

        file.unlink()

        deleted += 1

    print(f"Deleted {deleted} transaction CSV files (master data preserved).")