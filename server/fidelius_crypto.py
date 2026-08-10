"""
Fidelius Encryption for Health Information Transfer.

This is separate from server/crypto.py (which handles RSA-OAEP encryption
for ABHA/Aadhaar values -- an unrelated encryption need for M1). This
module implements ABDM's Fidelius scheme, used specifically to encrypt
FHIR bundles before pushing them to an HIU's dataPushUrl in M2.

WHY THIS IS PURE PYTHON, NOT A LIBRARY:
Fidelius uses a custom Curve25519 in Short Weierstrass form (BouncyCastle's
curve), NOT the standard Montgomery-form X25519 used in TLS/SSH. No
mainstream crypto library implements this specific form, and the natural
choice (pyfidelius, a Python port of ABDM's reference Java implementation)
depends on fastecdsa, which requires a C compiler and the GMP math library
to build -- a genuinely difficult, unreliable install on Windows with no
official fix as of this writing.

Since the only missing piece was the elliptic curve point arithmetic
itself (everything else -- HKDF, AES-256-GCM -- is already available via
the 'cryptography' package already in requirements.txt), this module
implements that curve arithmetic directly in pure Python. No new
dependency, works anywhere Python runs, no compiler needed.

VERIFIED against the official test vector published in ABDM's own
reference implementation's documentation (mgrmtech/fidelius-cli README) --
see tools/verify_fidelius.py. The curve parameters below were also
independently cross-checked against BouncyCastle's own published base
point encoding (bc-java CustomNamedCurves.java) before being used.

ALGORITHM (per ABDM's official "Encryption and Decryption Implementation
Guidelines for FHIR data in ABDM" document):
    1. ECDH: shared_secret = x-coordinate of (own_private_key * their_public_key)
    2. salt/IV: XOR the two 32-byte nonces together; first 20 bytes = HKDF
       salt, last 12 bytes = AES-GCM IV
    3. HKDF-SHA256(ikm=shared_secret, salt=salt, info=b"") -> 32-byte AES key
    4. AES-256-GCM(key, iv, plaintext) -> ciphertext + 16-byte auth tag
"""

import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


# ---------------------------------------------------------------------------
# BC25519 (Curve25519 in Short Weierstrass form) parameters.
#
# Derived from the standard Montgomery curve25519 constants (A=486662, B=1)
# via the documented substitution a=(3-A^2)/(3B^2), b=(2A^3-9A)/(27B^3),
# and cross-checked bit-for-bit against BouncyCastle's own published base
# point in bc-java's CustomNamedCurves.java.
# ---------------------------------------------------------------------------

_P = 2**255 - 19  # field prime (same as standard curve25519)
_N = 2**252 + 27742317777372353535851937790883648493  # subgroup order


def _inv(x, m=_P):
    return pow(x, m - 2, m)


_A_MONT = 486662
_CURVE_A = ((3 - _A_MONT * _A_MONT) * _inv(3)) % _P
_CURVE_B = ((2 * _A_MONT**3 - 9 * _A_MONT) * _inv(27)) % _P

# Base point G, from BouncyCastle's published uncompressed encoding
# (04 || X(32 bytes) || Y(32 bytes)) -- verified in tools/verify_fidelius.py
# to satisfy y^2 = x^3 + CURVE_A*x + CURVE_B (mod _P).
_G_HEX = (
    "042AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD245"
    "A20AE19A1B8A086B4E01EDD2C7748D14C923D4D7E6D7C61B229E9C5A27ECED3D9"
)
_G_BODY = _G_HEX[2:]
_G = (int(_G_BODY[:64], 16), int(_G_BODY[64:], 16))

_INFINITY = None


def _point_add(point_a, point_b):
    if point_a is _INFINITY:
        return point_b
    if point_b is _INFINITY:
        return point_a

    x1, y1 = point_a
    x2, y2 = point_b

    if x1 == x2 and (y1 + y2) % _P == 0:
        return _INFINITY

    if point_a == point_b:
        slope = (3 * x1 * x1 + _CURVE_A) * _inv(2 * y1) % _P
    else:
        slope = (y2 - y1) * _inv(x2 - x1) % _P

    x3 = (slope * slope - x1 - x2) % _P
    y3 = (slope * (x1 - x3) - y1) % _P

    return (x3, y3)


def _scalar_mult(scalar, point):
    result = _INFINITY
    addend = point
    while scalar:
        if scalar & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        scalar >>= 1
    return result


def _encode_public_key(point):
    x, y = point
    return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")


# X.509 SubjectPublicKeyInfo DER prefix for BC25519 (Curve25519 in Short
# Weierstrass form), with explicit domain parameters (this curve has no
# registered named-curve OID, so the full prime/a/b/basepoint/order/
# cofactor are embedded). Everything up to this prefix is identical for
# every key on this curve; only the raw 65-byte point differs.
#
# VERIFIED byte-for-byte against the real fidelius-cli reference tool's
# own `gkm` (generate-key-material) output for a known private key --
# confirmed this prefix + that key's raw 65-byte point reproduces the
# exact x509PublicKey the official tool produced. Not something I
# constructed from ASN.1 spec knowledge alone.
_X509_DER_PREFIX_HEX = "308201313081ea06072a8648ce3d02013081de020101302b06072a8648ce3d010102207fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffed304404202aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa984914a14404207b425ed097b425ed097b425ed097b425ed097b425ed097b4260b5e9c7710c8640441042aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaad245a20ae19a1b8a086b4e01edd2c7748d14c923d4d7e6d7c61b229e9c5a27eced3d902201000000000000000000000000000000014def9dea2f79cd65812631a5cf5d3ed020108034200"
_X509_DER_PREFIX = bytes.fromhex(_X509_DER_PREFIX_HEX)


def to_x509_public_key(raw_public_key_b64):
    """
    Converts a raw uncompressed-point public key (base64, 65 bytes, 0x04
    prefix -- the format used internally and for incoming ABDM keys) into
    the X.509 DER SubjectPublicKeyInfo format (base64) that ABDM's data-push
    endpoint expects for the outbound dhPublicKey.keyValue field.
    """
    raw_point = base64.b64decode(raw_public_key_b64)
    if len(raw_point) != 65 or raw_point[0] != 0x04:
        raise ValueError(f"Expected a 65-byte uncompressed point (0x04 prefix), got {len(raw_point)} bytes")
    return base64.b64encode(_X509_DER_PREFIX + raw_point).decode()


def from_x509_public_key(x509_public_key_b64):
    """
    Inverse of to_x509_public_key() -- strips the fixed X.509 DER
    SubjectPublicKeyInfo prefix off an incoming key and returns the raw
    uncompressed-point public key (base64) that decrypt_health_data()/
    _decode_public_key() expect.

    Added for M3 Block 2 (server/callbacks/services/
    health_information_hiu_push_service.py): when we (the HIU) receive an
    HIP's direct data push, its keyMaterial.dhPublicKey.keyValue arrives
    in this X.509 format -- mirroring what
    health_information_request_service.py's _push_and_notify() does for
    its OWN outbound key when M2 pushes to an HIU's dataPushUrl (see that
    function's comment: "Our own public key must be sent in X.509 DER
    format -- confirmed as the actual root cause of the earlier
    'ABDM-9999: Could not read encrypted content' 400 error"). Since this
    codebase runs both the HIP and HIU roles for sandbox testing, a push
    received at our own dataPushUrl in practice comes from our own M2
    code, which is confirmed to send X.509 -- this is the certain,
    matching inverse for that specific case, not a guess about every
    possible third-party HIP's behavior.
    """
    der_bytes = base64.b64decode(x509_public_key_b64)
    raw_point = der_bytes[len(_X509_DER_PREFIX):]
    if len(raw_point) != 65 or raw_point[0] != 0x04:
        raise ValueError(
            f"Expected a 65-byte uncompressed point (0x04 prefix) after "
            f"stripping the X.509 DER prefix, got {len(raw_point)} bytes"
        )
    return base64.b64encode(raw_point).decode()


def _decode_public_key(raw_bytes):
    if raw_bytes[0] != 0x04:
        raise ValueError(f"Expected uncompressed EC point (0x04 prefix), got {raw_bytes[0]:#x}")
    x = int.from_bytes(raw_bytes[1:33], "big")
    y = int.from_bytes(raw_bytes[33:65], "big")

    if (y * y - (x**3 + _CURVE_A * x + _CURVE_B)) % _P != 0:
        raise ValueError(f"Public key point is not on the curve (x={x}, y={y})")

    return (x, y)


def _derive_key_and_iv(sender_nonce_bytes, requester_nonce_bytes, shared_secret_x_bytes):
    if len(sender_nonce_bytes) != 32 or len(requester_nonce_bytes) != 32:
        raise ValueError(
            f"Expected 32-byte nonce, got sender={len(sender_nonce_bytes)} bytes, "
            f"requester={len(requester_nonce_bytes)} bytes"
        )

    xor_nonces = bytes(s ^ r for s, r in zip(sender_nonce_bytes, requester_nonce_bytes))
    salt = xor_nonces[:20]
    iv = xor_nonces[20:32]

    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"")
    aes_key = hkdf.derive(shared_secret_x_bytes)

    return aes_key, iv


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_key_material():
    """
    Generates a fresh ephemeral ECDH key pair + 32-byte nonce for one
    transaction. Per Fidelius's forward-secrecy design, this should be
    called freshly for every Health Information Request -- never reused
    across transactions.

    Returns:
        dict with keys: private_key, public_key, nonce
        (private_key and nonce are base64-encoded 32-byte values;
        public_key is the base64-encoded uncompressed point, matching
        the format ABDM's keyMaterial payload expects)
    """

    private_key_int = int.from_bytes(os.urandom(32), "big") % _N
    public_point = _scalar_mult(private_key_int, _G)

    return {
        "private_key": base64.b64encode(private_key_int.to_bytes(32, "big")).decode(),
        "public_key": base64.b64encode(_encode_public_key(public_point)).decode(),
        "nonce": base64.b64encode(os.urandom(32)).decode(),
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

    All key/nonce arguments are base64-encoded strings, matching what
    ABDM's payloads use.

    Returns:
        base64-encoded ciphertext string (includes the AES-GCM auth tag)
    """

    sender_priv_int = int.from_bytes(base64.b64decode(sender_private_key), "big")
    requester_pub_point = _decode_public_key(base64.b64decode(requester_public_key))

    shared_point = _scalar_mult(sender_priv_int, requester_pub_point)
    shared_secret_x_bytes = shared_point[0].to_bytes(32, "big")

    aes_key, iv = _derive_key_and_iv(
        base64.b64decode(sender_nonce),
        base64.b64decode(requester_nonce),
        shared_secret_x_bytes,
    )

    ciphertext = AESGCM(aes_key).encrypt(iv, plaintext.encode(), None)

    return base64.b64encode(ciphertext).decode()


def decrypt_health_data(
    ciphertext,
    sender_private_key,
    sender_nonce,
    requester_public_key,
    requester_nonce,
):
    """
    Inverse of encrypt_health_data() -- included for completeness and for
    self-testing (see tools/verify_fidelius.py), since the HIP side of
    ABDM's flow only ever calls encrypt_health_data() in production.
    """

    sender_priv_int = int.from_bytes(base64.b64decode(sender_private_key), "big")
    requester_pub_point = _decode_public_key(base64.b64decode(requester_public_key))

    shared_point = _scalar_mult(sender_priv_int, requester_pub_point)
    shared_secret_x_bytes = shared_point[0].to_bytes(32, "big")

    aes_key, iv = _derive_key_and_iv(
        base64.b64decode(sender_nonce),
        base64.b64decode(requester_nonce),
        shared_secret_x_bytes,
    )

    plaintext_bytes = AESGCM(aes_key).decrypt(iv, base64.b64decode(ciphertext), None)

    return plaintext_bytes.decode()
