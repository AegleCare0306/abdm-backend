"""
verify_fidelius.py

Verifies server/fidelius_crypto.py -- the pure-Python Fidelius encryption
implementation -- against a known test vector published in ABDM's own
reference implementation's documentation (mgrmtech/fidelius-cli README),
plus a self-consistent encrypt->decrypt round trip.

Unlike the earlier version of this script, this does NOT depend on any
external package beyond what's already in requirements.txt (no fastecdsa,
no GMP, no C compiler needed) -- server/fidelius_crypto.py implements the
BC25519 curve arithmetic directly in pure Python.

HOW TO RUN
----------
    pip install -r requirements.txt
    python verify_fidelius.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.fidelius_crypto import decrypt_health_data, encrypt_health_data, generate_key_material


KNOWN_CIPHERTEXT = (
    "pzMvVZNNVtJzqPkkxcCbBUWgDEBy/mBXIeT2dJWI16ZAQnnXUb9lI+S4k8XK6mgZ"
    "SKKSRIHkcNvJpllnBg548wUgavBa0vCRRwdL6kY6Yw=="
)
KNOWN_SENDER_NONCE = "6uj1RdDUbcpI3lVMZvijkMC8Te20O4Bcyz0SyivX8Eg="
KNOWN_REQUESTER_NONCE = "lmXgblZwotx+DfBgKJF0lZXtAXgBEYr5khh79Zytr2Y="
KNOWN_SENDER_PRIVATE_KEY = "DMxHPri8d7IT23KgLk281zZenMfVHSdeamq0RhwlIBk="
KNOWN_REQUESTER_PUBLIC_KEY = (
    "BABVt+mpRLMXiQpIfEq6bj8hlXsdtXIxLsspmMgLNI1SR5mHgDVbjHO2A+U4QlMd"
    "dGzqyEidzm1AkhtSxSO2Ahg="
)
EXPECTED_PLAINTEXT = "Wormtail should never have been Potter cottage's secret keeper."


def check_known_vector():
    print("[1/2] Known reference test vector (mgrmtech/fidelius-cli README)")
    try:
        result = decrypt_health_data(
            ciphertext=KNOWN_CIPHERTEXT,
            sender_private_key=KNOWN_SENDER_PRIVATE_KEY,
            sender_nonce=KNOWN_SENDER_NONCE,
            requester_public_key=KNOWN_REQUESTER_PUBLIC_KEY,
            requester_nonce=KNOWN_REQUESTER_NONCE,
        )
    except Exception as exc:
        print(f"  [FAIL] Raised {type(exc).__name__}: {exc}")
        return False

    if result == EXPECTED_PLAINTEXT:
        print(f'  [PASS] Decrypted exactly: "{result}"')
        return True

    print(f"  [FAIL] Expected: {EXPECTED_PLAINTEXT!r}")
    print(f"         Got:      {result!r}")
    return False


def check_round_trip():
    print("\n[2/2] Self-consistent encrypt -> decrypt round trip (fresh keys)")
    try:
        hip = generate_key_material()
        hiu = generate_key_material()
        message = '{"resourceType": "Bundle", "id": "verify-round-trip"}'

        ciphertext = encrypt_health_data(
            plaintext=message,
            sender_private_key=hip["private_key"],
            sender_nonce=hip["nonce"],
            requester_public_key=hiu["public_key"],
            requester_nonce=hiu["nonce"],
        )

        recovered = decrypt_health_data(
            ciphertext=ciphertext,
            sender_private_key=hiu["private_key"],
            sender_nonce=hiu["nonce"],
            requester_public_key=hip["public_key"],
            requester_nonce=hip["nonce"],
        )
    except Exception as exc:
        print(f"  [FAIL] Raised {type(exc).__name__}: {exc}")
        return False

    if recovered == message:
        print(f"  [PASS] Round trip recovered the original message exactly.")
        return True

    print(f"  [FAIL] Expected: {message!r}")
    print(f"         Got:      {recovered!r}")
    return False


def main():
    print("\nVerifying server/fidelius_crypto.py...\n")

    results = [check_known_vector(), check_round_trip()]

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed.\n")

    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
