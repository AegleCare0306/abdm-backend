"""
Organization Resource Builder.
"""

from fhir.resources.R4B.organization import Organization
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.contactpoint import ContactPoint
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.address import Address
from fhir.resources.R4B.meta import Meta


ABDM_ORGANIZATION_PROFILE = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Organization"
FACILITY_ID_SYSTEM = "https://facility.ndhm.gov.in"


def build_organization(organization_row):
    """
    organization_row expected keys (matches organizations.csv):
        hip_id, organization_name, organization_type, address_line1,
        city, state, pincode, phone, email
    """

    telecom = []
    if organization_row.get("phone"):
        telecom.append(ContactPoint(system="phone", value=organization_row["phone"]))
    if organization_row.get("email"):
        telecom.append(ContactPoint(system="email", value=organization_row["email"]))

    address_kwargs = {}
    if organization_row.get("address_line1"):
        address_kwargs["line"] = [organization_row["address_line1"]]
    if organization_row.get("city"):
        address_kwargs["city"] = organization_row["city"]
    if organization_row.get("state"):
        address_kwargs["state"] = organization_row["state"]
    if organization_row.get("pincode"):
        address_kwargs["postalCode"] = organization_row["pincode"]
    if address_kwargs:
        address_kwargs["country"] = "IN"

    kwargs = {
        "id": organization_row["hip_id"],
        "meta": Meta(profile=[ABDM_ORGANIZATION_PROFILE]),
        "identifier": [
            Identifier(system=FACILITY_ID_SYSTEM, value=organization_row["hip_id"])
        ],
        "name": organization_row["organization_name"],
    }

    if organization_row.get("organization_type"):
        kwargs["type"] = [CodeableConcept(text=organization_row["organization_type"])]

    if telecom:
        kwargs["telecom"] = telecom

    if address_kwargs:
        kwargs["address"] = [Address(**address_kwargs)]

    organization = Organization(**kwargs)

    return organization.model_dump(mode="json", exclude_none=True)
