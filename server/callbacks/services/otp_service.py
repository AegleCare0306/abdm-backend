from server.crypto import encrypt_value, get_public_certificate

from server.abha import verify_otp as abha_verify_otp

from server.utils import print_api_response
from server.callbacks.utils.flow_logger import log_api_call


def verify_otp(
    otp,
    txn_id,
):
    """
    Verifies the OTP entered by the patient.

    Args:
        otp (str): Plain text OTP entered by the patient.
        txn_id (str): OTP transaction ID.

    Returns:
        bool
    """

    encrypted_otp = encrypt_value(otp, get_public_certificate())

    response = abha_verify_otp(
        action="profile/login",
        scope=["abha-login", "mobile-verify"],
        txn_id=txn_id,
        otp_value=encrypted_otp,
    )

    log_api_call("Verifying OTP with ABDM", "POST .../profile/login/verify", response.status_code)

    if response.status_code != 200:
        print_api_response(response)
        return False

    return True