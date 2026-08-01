"""
Shared datetime formatting for FHIR resource builders.
"""


def to_fhir_datetime(value):
    """
    '2025-05-16 06:53:08' -> '2025-05-16T06:53:08+05:30'

    FHIR's dateTime type requires a timezone offset whenever a time
    component is present (its regex rejects a bare local time). The
    dummy data has no timezone info, so IST (+05:30) is appended since
    this is Indian hospital data -- if encounter_datetime ever starts
    carrying its own timezone, this should read that instead of assuming.
    """
    if not value:
        return None
    return value.replace(" ", "T") + "+05:30"
