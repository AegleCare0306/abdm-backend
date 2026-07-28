"""
Bundle Resource Builder.
"""

from fhir.resources.R4B.bundle import Bundle, BundleEntry
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.meta import Meta


ABDM_BUNDLE_PROFILE = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/DocumentBundle"
BUNDLE_ID_SYSTEM = "https://ndhm.in"


def build_bundle(*, bundle_id, composition, resources, timestamp):
    """
    Assembles a FHIR "document" Bundle from already-built resource dicts
    (the output of the other build_* functions) -- this function takes
    finished resources, not CSV rows, so it doesn't care where they came
    from.

    composition: the Composition resource dict (always entry[0] in a
        document Bundle, per the FHIR spec)
    resources: flat list of every other resource dict to include
        (Patient, Practitioner, Organization, Encounter, Condition(s),
        Observation(s), etc.)
    timestamp: FHIR instant string for Bundle.timestamp

    Every entry's fullUrl is set to "<ResourceType>/<id>" to match the
    literal reference style ("Patient/PAT9001" etc.) used by every other
    builder -- so references within the bundle resolve correctly.
    """

    entries = [
        BundleEntry(
            fullUrl=f"{composition['resourceType']}/{composition['id']}",
            resource=composition,
        )
    ]

    for resource in resources:
        entries.append(
            BundleEntry(
                fullUrl=f"{resource['resourceType']}/{resource['id']}",
                resource=resource,
            )
        )

    bundle = Bundle(
        id=bundle_id,
        meta=Meta(profile=[ABDM_BUNDLE_PROFILE]),
        identifier=Identifier(system=BUNDLE_ID_SYSTEM, value=bundle_id),
        type="document",
        timestamp=timestamp,
        entry=entries,
    )

    return bundle.model_dump(mode="json", exclude_none=True)
