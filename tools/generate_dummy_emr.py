"""
Dummy EMR Generator
"""


from dummy_emr.config import MASTER_OUTPUT_FOLDER,TRANSACTION_OUTPUT_FOLDER, RANDOM_SEED
from dummy_emr.csv_writer import write_csv
from dummy_emr.generators.organizations import generate_organizations
from dummy_emr.generators.practitioners import generate_practitioners
from dummy_emr.generators.patients import generate_patients
from dummy_emr.generators.practitioner_organizations import generate_practitioner_organizations
from dummy_emr.generators.encounters import generate_encounters
from dummy_emr.file_manager import clear_output_folder
from dummy_emr.generators.conditions import generate_conditions


import random


def main():
    random.seed(RANDOM_SEED)
    print("\nGenerating Dummy EMR...\n")
    clear_output_folder()
    organizations = generate_organizations()
    practitioners = generate_practitioners()
    practitioner_organizations = (generate_practitioner_organizations(practitioners))
    patients = generate_patients()
    encounters = generate_encounters(patients,practitioners,practitioner_organizations,)
    conditions = generate_conditions(encounters)

    write_csv(
        MASTER_OUTPUT_FOLDER,
        "organizations.csv",
        organizations,
    )
    write_csv(
        MASTER_OUTPUT_FOLDER,
        "practitioners.csv",
        practitioners,
    )
    write_csv(
        TRANSACTION_OUTPUT_FOLDER,
        "patients.csv",
        patients,
    )
    write_csv(
        MASTER_OUTPUT_FOLDER,
        "practitioner_organizations.csv",
        practitioner_organizations,
    )
    write_csv(
        TRANSACTION_OUTPUT_FOLDER,
        "encounters.csv",
        encounters,
    )
    write_csv(
        TRANSACTION_OUTPUT_FOLDER,
        "conditions.csv",
        conditions,
    )
    print("\nGeneration Complete.\n")


if __name__ == "__main__":
    main()