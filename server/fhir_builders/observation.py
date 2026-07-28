"""
Observation Resource Builder.
"""

from fhir.resources.R4B.observation import Observation, ObservationComponent
from fhir.resources.R4B.quantity import Quantity
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.meta import Meta


ABDM_OBSERVATION_PROFILE = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Observation"
LOINC_SYSTEM = "http://loinc.org"
UCUM_SYSTEM = "http://unitsofmeasure.org"

BP_OBSERVATION_REF = "OBS000001"
SYSTOLIC_LOINC = "8480-6"
DIASTOLIC_LOINC = "8462-4"

# observation_master_reference -> UCUM unit code (the CSV's "unit" field is a
# display string like "mmHg", not a UCUM code, so this maps explicitly rather
# than trying to string-match display units to UCUM)
UCUM_UNIT_MAP = {
    "OBS000001": "mm[Hg]",
    "OBS000002": "/min",
    "OBS000003": "/min",
    "OBS000004": "Cel",
    "OBS000005": "kg",
    "OBS000006": "cm",
    "OBS000007": "mg/dL",
    "OBS000008": "%",
}


def _to_fhir_datetime(value):
    if not value:
        return None
    return value.replace(" ", "T") + "+05:30"


def build_observation(observation_row):
    """
    observation_row expected keys (matches observations.csv):
        observation_reference, encounter_reference, patient_reference,
        observation_master_reference, name, loinc, value, unit,
        effective_datetime, status
    """

    master_ref = observation_row["observation_master_reference"]
    ucum_unit = UCUM_UNIT_MAP.get(master_ref)

    kwargs = {
        "id": observation_row["observation_reference"],
        "meta": Meta(profile=[ABDM_OBSERVATION_PROFILE]),
        "status": observation_row["status"],
        "code": CodeableConcept(
            coding=[Coding(system=LOINC_SYSTEM, code=observation_row["loinc"], display=observation_row["name"])],
            text=observation_row["name"],
        ),
        "subject": Reference(reference=f"Patient/{observation_row['patient_reference']}"),
        "encounter": Reference(reference=f"Encounter/{observation_row['encounter_reference']}"),
        "effectiveDateTime": _to_fhir_datetime(observation_row["effective_datetime"]),
    }

    if master_ref == BP_OBSERVATION_REF:
        # Blood Pressure is a panel: systolic/diastolic as separate
        # components with their own LOINC codes, not a single value.
        systolic, diastolic = observation_row["value"].split("/")
        kwargs["component"] = [
            ObservationComponent(
                code=CodeableConcept(coding=[Coding(system=LOINC_SYSTEM, code=SYSTOLIC_LOINC, display="Systolic blood pressure")]),
                valueQuantity=Quantity(value=float(systolic), unit=observation_row["unit"], system=UCUM_SYSTEM, code=ucum_unit),
            ),
            ObservationComponent(
                code=CodeableConcept(coding=[Coding(system=LOINC_SYSTEM, code=DIASTOLIC_LOINC, display="Diastolic blood pressure")]),
                valueQuantity=Quantity(value=float(diastolic), unit=observation_row["unit"], system=UCUM_SYSTEM, code=ucum_unit),
            ),
        ]
    else:
        kwargs["valueQuantity"] = Quantity(
            value=float(observation_row["value"]),
            unit=observation_row["unit"],
            system=UCUM_SYSTEM,
            code=ucum_unit,
        )

    observation = Observation(**kwargs)

    return observation.model_dump(mode="json", exclude_none=True)
