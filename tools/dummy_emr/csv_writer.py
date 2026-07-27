"""
CSV Writer.
"""

import csv
from pathlib import Path


def write_csv(
    folder,
    filename,
    rows,
):

    if not rows:
        return

    output_file = Path(folder) / filename

    with open(
        output_file,
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=rows[0].keys(),
        )

        writer.writeheader()

        writer.writerows(rows)

    print(f"Created {filename}")