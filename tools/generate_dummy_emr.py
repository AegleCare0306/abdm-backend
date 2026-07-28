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
from dummy_emr.generators.observations import generate_observations
from dummy_emr.generators.medication_requests import generate_medication_requests
from dummy_emr.generators.diagnostic_reports import generate_diagnostic_reports
from dummy_emr.generators.procedures import generate_procedures
from dummy_emr.generators.documents import generate_documents
from dummy_emr.generators.immunizations import generate_immunizations
from dummy_emr.generators.billing import generate_billing


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
    observations = generate_observations(encounters, patients)
    medication_requests = generate_medication_requests(encounters)
    diagnostic_reports = generate_diagnostic_reports(encounters)
    procedures = generate_procedures(encounters)
    documents = generate_documents(encounters)
    immunizations = generate_immunizations(encounters)
    billing = generate_billing(encounters, medication_requests, diagnostic_reports, procedures)

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
        MASTER_OUTPUT_FOLDER,
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
    write_csv(
        TRANSACTION_OUTPUT_FOLDER,
        "observations.csv",
        observations,
    )
    write_csv(
        TRANSACTION_OUTPUT_FOLDER,
        "medication_requests.csv",
        medication_requests,
    )
    write_csv(
        TRANSACTION_OUTPUT_FOLDER,
        "diagnostic_reports.csv",
        diagnostic_reports,
    )
    write_csv(
        TRANSACTION_OUTPUT_FOLDER,
        "procedures.csv",
        procedures,
    )
    write_csv(
        TRANSACTION_OUTPUT_FOLDER,
        "documents.csv",
        documents,
    )
    write_csv(
        TRANSACTION_OUTPUT_FOLDER,
        "immunizations.csv",
        immunizations,
    )
    write_csv(
        TRANSACTION_OUTPUT_FOLDER,
        "billing.csv",
        billing,
    )
    print("\nGeneration Complete.\n")


if __name__ == "__main__":
    main()