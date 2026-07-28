"""
FHIR R4 Resource Builders.

Permanent, reusable resource-construction logic for the ABDM HIP.

Each build_<resource>() function takes a plain dict of field values
(today: a row from the dummy EMR CSVs; later: a row from the real EMR
database) and returns a plain Python dict of the finished FHIR resource,
ready to drop into a Bundle or serialize to JSON. Builders are deliberately
decoupled from any particular data source — they don't know or care
whether the input dict came from a CSV, an ORM row, or an API payload, as
long as it has the expected keys.

Built against fhir.resources>=7.1.0 (R4B namespace, pydantic v2 — see
requirements.txt for why this version was chosen).
"""
