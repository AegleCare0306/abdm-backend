"""
Shared helpers for the M1 test CLI's flow modules.

Every flow needs the same handful of things -- prompting for raw input,
RSA-OAEP encrypting a value before it goes to ABDM, and printing results
consistently -- so those live here once instead of being copy-pasted into
every flow module. Flow modules stay focused on their own API sequence.
"""

import json
from datetime import datetime
from pathlib import Path

from server.crypto import get_public_certificate, encrypt_value
from server.utils import print_api_response

_LOG_DIR = Path(__file__).resolve().parent / "logs"
# One file per CLI process run (fixed at import time), not one per call --
# every log_response() call during this run appends to the same file.
_RUN_LOG_FILE = _LOG_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


def prompt(label):
    """Prompts for one line of raw (unencrypted) input, stripped."""
    return input(f"{label}: ").strip()


def encrypt(raw_value):
    """
    Encrypts a raw value (Aadhaar number, OTP, mobile, etc.) the way every
    ABDM field that expects encryption needs it -- RSA-OAEP against the
    (cached) ABDM public certificate. Reuses server.crypto directly rather
    than reimplementing anything.
    """
    public_key = get_public_certificate()
    return encrypt_value(raw_value, public_key)


def print_header(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def print_success(message):
    print(f"\n[OK] {message}")


def print_info(message):
    print(f"      {message}")


def print_failure(message):
    print(f"\n[FAIL] {message}")


def redact_token(value):
    """
    Returns a short, console-safe representation of a long/sensitive value
    (X-Token, T-Token, refresh token, etc.) -- just the last 8 characters,
    prefixed with "...". Enough to eyeball "something was returned" and
    spot-compare against the log file without ever putting the full JWT
    on the console. The full value should always still reach the log file
    via log_response() elsewhere (usually already captured as part of the
    raw response body) -- this function only controls what's SAFE TO PRINT.
    """
    if not value:
        return value
    value = str(value)
    if len(value) <= 8:
        return value
    return f"...{value[-8:]}"


def log_response(context, body):
    """
    Appends a full response body to this process run's log file under
    tools/m1_test_suite/logs/, instead of printing it to the console.
    Console output stays limited to the friendly summary lines
    (print_success()/print_info()/etc.) -- this is where the ground truth
    goes when a field name used by this CLI isn't confirmed against the
    live API (see each flow's own notes) so nothing is silently lost.

    Call this ONLY for successful responses. report_failure() already
    prints failures to the console in full via print_api_response() --
    logging them here too would just duplicate that.

    SENSITIVE: these log files contain full session tokens (JWTs), OTPs,
    ABHA numbers, and mobile numbers in plaintext (Aadhaar numbers are
    RSA-encrypted before being sent, so those don't appear here). This
    directory is gitignored specifically because of this -- never paste
    its contents anywhere; treat it as sensitive local-only debug output.
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "context": context,
        "body": body,
    }

    with open(_RUN_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, indent=2, default=str) + "\n")


def first_present(body, *keys, default=None):
    """
    Returns the first non-None value among `keys` in `body`. Used where a
    field's exact JSON key isn't confirmed by documentation -- a plausible
    key still surfaces the value without silently hiding it if the guess
    is wrong, and log_response() alongside it always preserves the ground
    truth (to the log file, not the console -- see that function).
    """
    for key in keys:
        value = body.get(key)
        if value is not None:
            return value
    return default


def report_failure(response, context):
    """
    Standard failure path for a non-success API response: a clear
    human-readable message, then the full response via print_api_response()
    -- the same error-reporting convention the rest of the codebase uses.
    """
    print_failure(f"{context} (status {response.status_code}).")
    print_api_response(response)


def print_accounts(accounts):
    """
    Prints a returned `accounts` list (the Verify OTP response shape:
    [{name, ABHANumber, preferredAbhaAddress, ...}, ...] -- or the
    "users" shape live-confirmed for the phr/web/login/abha action:
    [{fullName, abhaNumber, abhaAddress, ...}, ...]) with a friendly
    summary line plus the full entry logged via log_response(), via
    first_present() since the exact per-account key names aren't
    confirmed by documentation for every action -- see the login flow
    modules' own field-name notes.
    """
    if not accounts:
        print_info("No accounts were returned.")
        return

    print_info(f"{len(accounts)} account(s) returned:")
    for i, account in enumerate(accounts, start=1):
        name = first_present(account, "name", "fullName")
        abha_number = first_present(account, "ABHANumber", "healthIdNumber", "abhaNumber")
        abha_address = first_present(account, "preferredAbhaAddress", "phrAddress", "abhaAddress")
        print_info(f"  [{i}] {name}  |  ABHA Number: {abha_number}  |  ABHA Address: {abha_address}")
        log_response(f"account [{i}]", account)


def select_account(accounts):
    """
    Auto-selects the only entry when `accounts` has exactly one; otherwise
    prints a numbered list (name / ABHA Number) and prompts the user to
    pick. Shared by every login flow that needs the user to choose among
    multiple returned ABHA accounts (currently only "Login using Mobile
    Number" needs this, for its account-selection step before
    verify_user() -- kept here since Stage 3 flows may need it too).

    NOTE: the Search ABHA Account response (Flows 8/9) has a differently
    shaped per-entry list (it carries "index", which this "accounts" shape
    doesn't) -- that uses its own small local selection helper in
    flows/login_search.py rather than this one. See that module's notes.
    """
    if len(accounts) == 1:
        print_info("Exactly one account returned -- auto-selecting it.")
        return accounts[0]

    print_info(f"{len(accounts)} accounts returned -- choose one:")
    for i, account in enumerate(accounts, start=1):
        name = first_present(account, "name", "fullName")
        abha_number = first_present(account, "ABHANumber", "healthIdNumber", "abhaNumber")
        print_info(f"  [{i}] {name}  |  ABHA Number: {abha_number}")

    while True:
        choice = prompt(f"Enter a number (1-{len(accounts)})")
        if choice.isdigit() and 1 <= int(choice) <= len(accounts):
            return accounts[int(choice) - 1]
        print_info("Invalid choice, try again.")
