"""
verify_fidelius.py

Verifies that pyfidelius produces results matching ABDM's official
reference implementation (fidelius-cli, the Java project pyfidelius is
ported from), using a test vector published in that project's own README
-- NOT something I generated myself, since I have no way to independently
verify correct output for a curve this unusual.

Source of the test vector: mgrmtech/fidelius-cli README, the documented
encrypt/decrypt example pair. If this script prints PASS, the underlying
curve arithmetic + HKDF + AES-GCM chain in pyfidelius matches the real
ABDM spec -- since decrypt necessarily exercises the identical shared-
secret computation and key derivation that encrypt also depends on.

HOW TO RUN
----------
    pip install -r requirements.txt
    python verify_fidelius.py
"""

import sys

try:
    from fidelius import CryptoController, DecryptionRequest
except ImportError as exc:
    print(f"[FAIL] Could not import pyfidelius: {exc}")
    print("       Check `pip show fidelius` -- the class names below")
    print("       (DecryptionRequest, CryptoController.decrypt) are my")
    print("       best guess at the API surface; if the import itself")
    print("       fails, paste the actual error and I'll adjust.")
    sys.exit(1)


# Published test vector from mgrmtech/fidelius-cli's README.
# This is A (the "sender" in the original encrypt direction) having
# encrypted a message for B; here B ("sender" from B's own decrypt
# call's point of view) decrypts it back.
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


def main():

    print("\nVerifying pyfidelius against the official reference test vector...\n")

    try:
        decryption_request = DecryptionRequest(
            encrypted_data=KNOWN_CIPHERTEXT,
            sender_nonce=KNOWN_SENDER_NONCE,
            requester_nonce=KNOWN_REQUESTER_NONCE,
            sender_private_key=KNOWN_SENDER_PRIVATE_KEY,
            requester_public_key=KNOWN_REQUESTER_PUBLIC_KEY,
        )
        controller = CryptoController()
        result = controller.decrypt(decryption_request)
    except Exception as exc:
        print(f"[FAIL] Decryption raised an exception: {type(exc).__name__}: {exc}")
        print("       This likely means the DecryptionRequest/decrypt() API")
        print("       surface doesn't match what I guessed -- paste this error")
        print("       and I'll fix the call to match the real signature.")
        sys.exit(1)

    if result == EXPECTED_PLAINTEXT:
        print("[PASS] Decrypted output matches the known reference plaintext exactly.")
        print(f"       -> \"{result}\"")
        print("\npyfidelius's curve/HKDF/AES-GCM implementation matches the official spec.\n")
    else:
        print("[FAIL] Decrypted output does NOT match the expected plaintext.")
        print(f"       Expected: {EXPECTED_PLAINTEXT!r}")
        print(f"       Got:      {result!r}")
        print("\nThis would mean pyfidelius's output diverges from the official reference --")
        print("do not wire this into the live flow until this is resolved.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
