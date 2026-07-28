"""
Fidelius Encryption for Health Information Transfer.

This is separate from server/crypto.py (which handles RSA-OAEP encryption
for ABHA/Aadhaar values -- an unrelated encryption need for M1). This
module implements ABDM's Fidelius scheme, used specifically to encrypt
FHIR bundles before pushing them to an HIU's dataPushUrl in M2.

Fidelius uses a custom Curve25519 in Short Weierstrass form (BouncyCastle's
curve), NOT the standard Montgomery-form X25519 used in TLS/SSH -- this is
why a purpose-built library (pyfidelius, a Python port of ABDM's own
reference Java implementation) is used here rather than the general
'cryptography' package already in requirements.txt. Using standard X25519
would silently produce a different shared secret and the HIU would fail
to decrypt, with no error on our side to indicate why.
"""

from fidelius import KeyMaterial, CryptoController, EncryptionRequest


def generate_key_material():
    """
    Generates a fresh ephemeral ECDH key pair + 32-byte nonce for one
    transaction. Per Fidelius's forward-secrecy design, this should be
    called freshly for every Health Information Request -- never reused
    across transactions.

    Returns:
        dict with keys: private_key, public_key, nonce
        (all base64-encoded strings, matching what ABDM's keyMaterial
        payload format expects)
    """

    key_material = KeyMaterial.generate()

    return {
        "private_key": key_material.private_key,
        "public_key": key_material.public_key,
        "nonce": key_material.nonce,
    }


def encrypt_health_data(
    plaintext,
    sender_private_key,
    sender_nonce,
    requester_public_key,
    requester_nonce,
):
    """
    Encrypts plaintext (the FHIR bundle, as a JSON string) for transfer
    to an HIU.

    In ABDM's terminology, "sender" is us (the HIP) and "requester" is
    the HIU -- sender_private_key/sender_nonce should be our own freshly
    generated key_material (from generate_key_material() above), and
    requester_public_key/requester_nonce come from the keyMaterial the
    HIU sent us in the original Health Information Request.

    Returns:
        base64-encoded ciphertext string (includes the AES-GCM auth tag)
    """

    encryption_request = EncryptionRequest(
        sender_nonce=sender_nonce,
        requester_nonce=requester_nonce,
        sender_private_key=sender_private_key,
        requester_public_key=requester_public_key,
        string_to_encrypt=plaintext,
    )

    controller = CryptoController()

    return controller.encrypt(encryption_request)
