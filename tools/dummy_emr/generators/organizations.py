"""
Organization Generator.
"""

from dummy_emr.config import HIPS


def generate_organizations():

    organizations = []

    for organization in HIPS:

        organizations.append(
            {
                "hip_id": organization["hip_id"],
                "organization_name": organization["name"],
                "organization_type": organization["organization_type"],
                "address_line1": organization["address_line1"],
                "city": organization["city"],
                "state": organization["state"],
                "pincode": organization["pincode"],
                "phone": organization["phone"],
                "email": organization["email"],
            }
        )

    return organizations