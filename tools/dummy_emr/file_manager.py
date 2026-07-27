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
    Deletes every generated CSV.
    """

    create_output_folders()

    deleted = 0

    for file in BASE_OUTPUT_FOLDER.rglob("*.csv"):

        file.unlink()

        deleted += 1

    print(f"Deleted {deleted} CSV files.")