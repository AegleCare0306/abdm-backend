"""
CSV Writer.
"""

import csv
import re
from pathlib import Path


def write_csv(
    folder,
    filename,
    rows,
):
    """
    Full overwrite. Only safe for output that is fully deterministic given
    a fixed random seed and a fixed call order (organizations.csv,
    practitioners.csv, practitioner_organizations.csv) -- anything
    patient- or encounter-scoped must go through upsert_csv() instead so a
    partial/subset run never destroys other patients' data.
    """

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


def read_csv(folder, filename):
    """Returns the existing rows as a list of dicts, or [] if the file
    doesn't exist yet."""

    path = Path(folder) / filename

    if not path.exists():
        return []

    with open(path, newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def upsert_csv(
    folder,
    filename,
    new_rows,
    key_fields,
    fieldnames=None,
):
    """
    Merge, not overwrite: loads whatever already exists, replaces/adds only
    the rows whose key matches a row in new_rows, and leaves every other
    existing row byte-for-byte untouched. Row order is preserved for
    existing rows; new keys are appended at the end.

    key_fields: tuple of column names that together form the row's key
        (e.g. ("encounter_reference",) or ("patient_reference",)).
    """

    if not new_rows:
        return

    existing_rows = read_csv(folder, filename)

    def key_of(row):
        return tuple(row[field] for field in key_fields)

    merged = {key_of(row): row for row in existing_rows}
    order = [key_of(row) for row in existing_rows]

    for row in new_rows:
        k = key_of(row)
        if k not in merged:
            order.append(k)
        merged[k] = row

    output_rows = [merged[k] for k in order]

    output_file = Path(folder) / filename

    if fieldnames is None:
        fieldnames = list(output_rows[0].keys())

    with open(
        output_file,
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Upserted {len(new_rows)} row(s) into {filename} ({len(output_rows)} total)")


def next_reference_index(folder, filename, ref_column, prefix):
    """
    Reads the existing CSV and returns one past the highest N found in
    values of ref_column matching "{prefix}{N}" (e.g. prefix="OBS" matches
    "OBS0001" -> 1). Returns 1 if the file doesn't exist or has no matching
    values yet. Used so a brand-new row's own reference ID (observation_
    reference, medication_request_reference, etc.) always continues
    forward from whatever is already on disk instead of restarting a
    fresh in-memory counter at 1 every run -- which would collide with
    already-used IDs belonging to other patients/encounters.
    """

    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")

    best = 0
    for row in read_csv(folder, filename):
        match = pattern.match(row.get(ref_column, ""))
        if match:
            best = max(best, int(match.group(1)))

    return best + 1


def max_numeric_suffix(values, pattern):
    """
    Given an iterable of strings and a compiled regex with one capturing
    group around the numeric part, returns the max captured integer (0 if
    none match). Used for facility-scoped running counters (mr_number,
    facility_encounter_number) whose format isn't a simple fixed prefix.
    """

    best = 0
    for value in values:
        match = pattern.match(value)
        if match:
            best = max(best, int(match.group(1)))
    return best
