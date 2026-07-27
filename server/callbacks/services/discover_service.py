from server.callbacks.repository.patient_repository import search_patient
from server.callbacks.transformers.patient_transformer import build_patient_payload
from server.linking import send_on_discover
from server.utils import print_api_response
from server.callbacks.repository.patient_identity_repository import save_patient_identity

import json

async def process_discover(callback_data):

    headers = callback_data["headers"]
    body = callback_data["body"]
    patient = body["patient"]

    verified = patient.get("verifiedIdentifiers", [])
    unverified = patient.get("unverifiedIdentifiers", [])

    hip_id = headers.get("x-hip-id")
    abha_address = None
    abha_number = None
    mobile = None
    mr_number = None

    for identifier in verified:

        if identifier["type"] == "MOBILE":
            mobile = identifier["value"]

        if identifier["type"] == "ABHA_NUMBER":
            abha_number = identifier["value"]

        if identifier["type"] == "abhaAddress":
            abha_address = identifier["value"]

    for identifier in unverified:

        if identifier["type"] == "MR":
            mr_number = identifier["value"]

    name = patient.get("name")
    gender = patient.get("gender")
    year_of_birth = patient.get("yearOfBirth")

    patient_profile= {
        "abha_address": abha_address,
        "abha_number": abha_number,
        "mobile": mobile,
        "name": name,
        "year_of_birth": year_of_birth,
        "hip_id": hip_id,
    }

    save_patient_identity(
        abha_address,
        patient_profile,
    )

    transaction_id = body.get("transactionId")
    request_id = headers.get("request-id")

    print("\n===== DISCOVER CALLBACK =====")

    patient_data = search_patient(
    abha_address=abha_address,
    hip_id=hip_id,
    )
    patient_payload = build_patient_payload(patient_data)

    print("Patient Found  :", patient_data)

    response = send_on_discover(
        transaction_id,
        request_id,
        patient_payload,
    )

    print("\n===== ON DISCOVER RESPONSE =====")
    print(f"Status Code : {response.status_code}")

    if response.status_code != 202:
        print_api_response(response)