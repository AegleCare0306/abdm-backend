"""
Billing Generator.
"""

from dummy_emr.case_library import CLINICAL_CASES
from dummy_emr.master_data.billing_catalog import BILLING
from dummy_emr.master_data.medications import MEDICATIONS
from dummy_emr.master_data.lab_tests import LAB_TESTS
from dummy_emr.master_data.procedures import PROCEDURES
from dummy_emr.utils import invoice_reference


def generate_billing(
    encounters,
    medication_requests,
    diagnostic_reports,
    procedures,
    start_index=1,
):

    billing = []

    case_lookup = {
        case["case_id"]: case
        for case in CLINICAL_CASES
    }

    medication_price = {
        med["medication_reference"]: med["base_price"]
        for med in MEDICATIONS
    }

    lab_price = {
        lab["lab_reference"]: lab["base_price"]
        for lab in LAB_TESTS
    }

    procedure_price = {
        proc["procedure_reference"]: proc["base_price"]
        for proc in PROCEDURES
    }

    meds_by_encounter = {}
    for med_request in medication_requests:
        meds_by_encounter.setdefault(
            med_request["encounter_reference"], []
        ).append(med_request)

    labs_by_encounter = {}
    for report in diagnostic_reports:
        labs_by_encounter.setdefault(
            report["encounter_reference"], []
        ).append(report)

    procedures_by_encounter = {}
    for procedure in procedures:
        procedures_by_encounter.setdefault(
            procedure["encounter_reference"], []
        ).append(procedure)

    investigation_markup = BILLING["investigation_markup"]
    pharmacy_markup = BILLING["pharmacy_markup"]

    invoice_counter = start_index

    for encounter in encounters:

        case = case_lookup[encounter["clinical_case"]]

        consultation_fee = BILLING["consultation"][case["billing_profile"]]

        pharmacy_charge = 0
        for med_request in meds_by_encounter.get(encounter["encounter_reference"], []):
            unit_price = medication_price[med_request["medication_reference"]]
            quantity = med_request["quantity"] or 1
            pharmacy_charge += unit_price * quantity

        pharmacy_charge = round(pharmacy_charge * pharmacy_markup, 2)

        investigation_charge = 0
        for report in labs_by_encounter.get(encounter["encounter_reference"], []):
            investigation_charge += lab_price[report["lab_reference"]]

        investigation_charge = round(investigation_charge * investigation_markup, 2)

        procedure_charge = sum(
            procedure_price[procedure["procedure_master_reference"]]
            for procedure in procedures_by_encounter.get(encounter["encounter_reference"], [])
        )

        total_amount = round(
            consultation_fee
            + pharmacy_charge
            + investigation_charge
            + procedure_charge,
            2,
        )

        billing.append(
            {
                "invoice_reference": invoice_reference(invoice_counter),
                "encounter_reference": encounter["encounter_reference"],
                "patient_reference": encounter["patient_reference"],
                "hip_id": encounter["hip_id"],
                "consultation_fee": consultation_fee,
                "pharmacy_charge": pharmacy_charge,
                "investigation_charge": investigation_charge,
                "procedure_charge": procedure_charge,
                "total_amount": total_amount,
                "currency": "INR",
                "status": "billed",
                "invoice_date": encounter["encounter_datetime"][:10],
            }
        )

        invoice_counter += 1

    return billing
