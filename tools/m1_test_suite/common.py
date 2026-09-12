"""
Shared helpers for the M1 test CLI's flow modules.

Every flow needs the same handful of things -- prompting for raw input,
RSA-OAEP encrypting a value before it goes to ABDM, and printing results
consistently -- so those live here once instead of being copy-pasted into
every flow module. Flow modules stay focused on their own API sequence.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from server.crypto import get_public_certificate, encrypt_value
from server.utils import print_api_response

_LOG_DIR = Path(__file__).resolve().parent / "logs"
# One file per CLI process run (fixed at import time), not one per call --
# every log_response() call during this run appends to the same file.
_RUN_LOG_FILE = _LOG_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Shared across every OTP-entry step in the M1 CLI (enrollment.py,
# login_runner.py) -- moved here 2026-08-17 so both modules use the same
# constant instead of each defining their own copy that could drift.
MAX_OTP_ATTEMPTS = 3

# Same pattern, for the identifier-entry retry loop added 2026-08-18 (Aayush:
# Incase of invalid mobile/aadhaar/abha display message and all to retry no
# quit) -- request_login_otp()/run_login_variant() below let the user
# re-enter a wrong/unrecognized Aadhaar, Mobile, ABHA Number, or ABHA
# Address up to this many times instead of quitting the flow on the first
# miss.
MAX_IDENTIFIER_ATTEMPTS = 3


def prompt(label):
    """Prompts for one line of raw (unencrypted) input, stripped."""
    return input(f"{label}: ").strip()


def prompt_digits(label, length, field_name):
    """
    Prompts for a value that must be EXACTLY `length` digits (0-9 only,
    nothing else -- no letters, spaces, dashes, symbols), re-prompting on
    anything else instead of guessing or sanitizing. Added 2026-08-18 per
    the 2026-08-14 standing rule (Aayush: "whenever a fix is made for
    Aadhaar input, or any other numeric-only field, it must be an EXACT
    match / allowlist... reject/strip anything outside that exact allowed
    set rather than best-effort sanitizing"), which had been decided but
    not yet actually implemented anywhere -- confirmed as a real, live gap
    via a teammate's MS Testing Notes session 2026-08-18: a non-12-digit
    Aadhaar number, a non-numeric Aadhaar number, and a non-10-digit/
    spaced mobile number were all sent to ABDM unvalidated and came back
    as a raw, unclean 400 dump ("LoginId is invalid" / "Invalid Mobile
    Number") -- the exact "no clean message" failure mode this project's
    standing rules say must always be fixed.

    Same allowlist standard as create_abha_address.py's Y/n guard
    (tracker case M1-41): reject and re-prompt, don't strip/truncate/
    guess at what the user meant.
    """
    while True:
        value = prompt(label)
        if len(value) == length and value.isdigit():
            return value
        print_failure(f"{field_name} must be exactly {length} digits (0-9 only) -- got {value!r}. Please try again.")


def _strip_number_separators(value):
    """
    Strips dashes AND whitespace (spaces/tabs) from a value -- used by
    prompt_aadhaar()/prompt_abha_number() below, per Aayush's revised rule
    (2026-08-18): Aadhaar and ABHA Number should accept dash-separated,
    space-separated, or unseparated digit groups -- we accept everything
    and send the required (plain-digit) format to ABDM. This SUPERSEDES
    the 2026-08-14 standing rule (exact-match-allowlist, reject anything
    outside the allowed character set) for these two fields specifically.
    Mobile and OTP are UNCHANGED -- still strict digit-only via
    prompt_digits() -- since Aayush's revised rule only named Aadhaar and
    ABHA.
    """
    return re.sub(r"[\s-]", "", value)


def prompt_aadhaar(label):
    """
    Prompts for an Aadhaar number, accepting dash-separated
    ("1234-5678-9012"), space-separated ("1234 5678 9012"), or plain
    ("123456789012") form -- strips separators, requires exactly 12
    digits after stripping. Added 2026-08-18 per Aayush's revised rule
    (see _strip_number_separators() above) -- replaces the strict
    prompt_digits(label, 12, "Aadhaar number") call previously used for
    every Aadhaar prompt (Flow 1, Flow 2), which was rejecting
    validly-formatted Aadhaar numbers just because they had dashes/spaces.
    """
    while True:
        value = prompt(label)
        digits_only = _strip_number_separators(value)
        if len(digits_only) == 12 and digits_only.isdigit():
            return digits_only
        print_failure(
            f"Aadhaar number must be 12 digits -- dashes and spaces are fine "
            f"(e.g. 1234-5678-9012, 1234 5678 9012, or 123456789012) -- got {value!r}. Please try again."
        )


def prompt_abha_number(label):
    """
    Prompts for an ABHA Number, accepting dash-separated
    ("91-1234-5678-9012"), space-separated ("91 1234 5678 9012"), or
    plain ("91123456789012") form -- 14 digits total, separators purely
    cosmetic ON INPUT.

    REAL BUG FOUND + FIXED 2026-08-18 (Aayush: "The ABHA number is still
    failing... i tried with and without dashes both fail"): this used to
    return the PLAIN 14-digit string regardless of input style. Both a
    dashed and a dash-free INPUT were being normalized to that same plain
    string, so of course both "failed the same way" -- they were sending
    the IDENTICAL (wrong) value to ABDM. Live capture confirmed ABDM
    rejects the plain-digit form with 400 "LoginId is invalid", while
    every ABHA Number ABDM itself has ever returned in a response body
    (e.g. "ABHANumber": "91-6182-1610-5253") uses the DASHED 2-4-4-4
    format -- that's the format ABDM's API actually wants back. Now
    re-formats to that dashed canonical form before returning/sending,
    regardless of how the user typed it -- this is what "accept
    everything ... and send the required format" (Aayush, 2026-08-18)
    actually means: normalize TO ABDM's required format, not just to
    plain digits.
    """
    while True:
        value = prompt(label)
        digits_only = _strip_number_separators(value)
        if len(digits_only) == 14 and digits_only.isdigit():
            return f"{digits_only[0:2]}-{digits_only[2:6]}-{digits_only[6:10]}-{digits_only[10:14]}"
        print_failure(
            f"ABHA Number must be 14 digits -- dashes and spaces are fine (e.g. "
            f"91-1234-5678-9012, 91 1234 5678 9012, or 91123456789012) -- got {value!r}. Please try again."
        )


_ABHA_ADDRESS_SUFFIX = "@sbx"


def prompt_abha_address(label):
    """
    Prompts for a full ABHA Address (the login form -- "someone@sbx", not
    just the "someone" part create_abha_address.py's own prompt takes).
    Confirmed format 2026-08-18 (Aayush): the local part (before "@sbx")
    must be alphanumeric plus '.', '_', '-' only. Rejects/re-prompts on
    anything else -- missing/wrong suffix, empty local part, or a
    disallowed character in it -- rather than guessing.
    """
    import re
    while True:
        value = prompt(label)
        if value.endswith(_ABHA_ADDRESS_SUFFIX):
            local_part = value[: -len(_ABHA_ADDRESS_SUFFIX)]
            if local_part and re.fullmatch(r"[A-Za-z0-9._-]+", local_part):
                return value
        print_failure(
            f'ABHA Address must be alphanumeric (plus ".", "_", "-") followed by '
            f'"{_ABHA_ADDRESS_SUFFIX}" (e.g. "someone{_ABHA_ADDRESS_SUFFIX}") -- got {value!r}. Please try again.'
        )


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


class RetryableIdentifierError(Exception):
    """
    Raised by request_login_otp() (only when
    raise_on_retryable_identifier_error=True) when a KNOWN
    identifier-invalid/not-found signature matched -- e.g. a wrong Aadhaar
    number, an unregistered ABHA Number/Address, or an ABDM-rejected
    mobile number. Lets the caller re-prompt for a corrected identifier
    and retry instead of the whole flow silently quitting on a mistake
    the user can just fix (Aayush, 2026-08-18: "Incase of invalid
    mobile/aadhaar/abha display message and all to retry no quit").

    Deliberately NOT raised for the Aadhaar-gateway-unavailable case
    (unrelated to what the user typed -- retrying immediately wouldn't
    help, per the earlier "fail fast" decision) or for any unrecognized
    failure shape (still a raw dump + quit, since we don't know yet
    whether re-entering the identifier would even help).
    """

    def __init__(self, message):
        super().__init__(message)
        self.message = message


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

    Originally "successful responses only" (report_failure() printed
    failures to the console in full via print_api_response(), so logging
    them here too would have just duplicated that). Extended 2026-08-17:
    now ALSO used for a failure whose cause is a KNOWN, classified error
    signature (see report_failure()'s known_signatures param below) --
    those show a clean message on the console instead of the raw dump,
    so the raw body needs to land somewhere so it isn't lost entirely.
    Still never call this for an UNCLASSIFIED failure -- report_failure()
    already prints those in full via print_api_response(), so logging
    them here too would duplicate that, same as before.

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


def classify_failure(response, known_signatures):
    """
    Checks a failed response's body against a list of known error
    signatures and returns the first match, or None if none match
    (including if the body isn't valid JSON, or isn't a dict).

    known_signatures: a list of {"match": fn(body) -> bool, "message": str}
    dicts, checked in order. Each entry must be based on a CONFIRMED real
    sandbox response + an explicit confirmation of what it actually means
    -- never guessed at from the error text alone (Aayush, 2026-08-17: raw
    ABDM error labels can be misleading -- e.g. a wrong-OTP failure during
    enrollment comes back as {"mobile": "Invalid Mobile Number", ...},
    nothing about it says "OTP" -- so a signature only belongs in this list
    once its real meaning has actually been verified).

    Callers that need to know WHICH signature matched (e.g. to decide
    whether to retry) should call this directly instead of going through
    report_failure() below.
    """
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    for signature in known_signatures:
        if signature["match"](body):
            return signature
    return None


def report_failure(response, context, known_signatures=None):
    """
    Standard failure path for a non-success API response.

    Default behavior (no known_signatures passed, or none match): a clear
    human-readable message, then the full response via print_api_response()
    -- the same error-reporting convention the rest of the codebase uses.
    This is deliberate for any failure shape we haven't classified yet
    (Aayush, 2026-08-17): showing the full raw detail on a NEW/unrecognized
    failure is what lets the actual cause get identified later and a
    known_signatures entry added for it -- rather than the console just
    going quiet on something we don't actually understand yet.

    known_signatures (optional): once a specific error signature has been
    CONFIRMED (see classify_failure()'s docstring -- real sandbox run +
    explicit confirmation of what it means, never guessed), pass it here
    so a match prints a clean, specific message instead of the raw dump.
    The raw body is still preserved even then -- written to this run's log
    file via log_response(), just not printed to the console.
    """
    if known_signatures:
        signature = classify_failure(response, known_signatures)
        if signature is not None:
            print_failure(signature["message"])
            log_response(f"{context} (known failure signature, status {response.status_code})", response.json())
            return

    print_failure(f"{context} (status {response.status_code}).")
    print_api_response(response)


def is_aadhaar_gateway_unavailable(response):
    """
    Detects ABDM's Aadhaar-OTP-gateway-unavailable failure -- CONFIRMED
    real 2026-08-18 (Aayush's own live run + a teammate's captured
    session): every OTP-request call using otp_system="aadhaar" failed
    for roughly 9+ minutes that day, in one of two observed shapes:

      1. HTTP 401 with an EMPTY body (no JSON at all -- just a generic
         "WWW-Authenticate: Basic realm=\"Realm\"" gateway-level auth
         challenge). This is NOT one of ABDM's own documented JSON error
         shapes, and NOT a real credential problem on our side: the exact
         same cached bearer token succeeded moments before/after on
         otp_system="abdm" (mobile-OTP) calls in the same run. This looks
         like an upstream gateway/proxy bouncing the request because the
         real Aadhaar-OTP backend it routes to is down.
      2. HTTP 400 with ABDM's own explicit
         {"code": "ABDM-9999", "message": "Aadhaar Gateway is unavailable"}
         -- direct confirmation from ABDM itself of an outage, seen in the
         same session (a different endpoint, phr/web/login/abha).

    Only meaningful for a request that used otp_system="aadhaar" -- a 401
    on an otp_system="abdm" (mobile) call means something different (a
    genuine auth problem) and must NOT be classified this way. Callers
    are responsible for checking otp_system themselves before calling
    this (this function has no way to know what was sent).
    """
    if response.status_code == 401:
        try:
            response.json()
            return False
        except ValueError:
            return True
    if response.status_code == 400:
        try:
            body = response.json()
        except ValueError:
            return False
        # Message check added 2026-08-18 (real-log follow-up): ABDM-9999
        # is NOT exclusive to the gateway-outage case -- a live run the
        # same day showed the SAME code with message "User not found" for
        # a nonexistent ABHA Address (see login_runner.py's
        # _ABHA_ADDRESS_NOT_FOUND_SIGNATURE). Checking code alone would
        # have misclassified that as "gateway unavailable" instead of
        # "account not found" wherever this check is reachable for an
        # otp_system="aadhaar" call. Requiring "unavailable" in the
        # message keeps this matching only the actually-confirmed outage
        # shape.
        return (
            isinstance(body, dict)
            and body.get("code") == "ABDM-9999"
            and "unavailable" in str(body.get("message", "")).lower()
        )
    return False


def report_aadhaar_gateway_unavailable(response, context):
    """
    Clean-message path for is_aadhaar_gateway_unavailable() -- mirrors
    report_failure()'s known-signature behavior (clean console message,
    raw detail preserved in the log file) but lives separately since this
    check needs the whole response object (status code + a possibly-empty
    body), not just a parsed JSON body the way classify_failure()'s
    known_signatures list expects.
    """
    print_failure(
        f"{context}: ABDM's Aadhaar OTP gateway appears to be unavailable right now "
        f"(status {response.status_code}). This is not a bug in this tool -- try again "
        f"in a few minutes, or use a mobile-number-based flow instead if this case allows it."
    )
    try:
        body = response.json()
    except ValueError:
        body = response.text
    log_response(f"{context} (Aadhaar gateway unavailable, status {response.status_code})", body)


def report_connection_error(exc, context):
    """
    Failure path for a connection-level exception (timeout, DNS,
    connection refused) -- as opposed to report_failure() above, which
    is for a response we actually got back from ABDM. Added for tracker
    cases M1-21/M1-22: before this, a RequestException raised out of
    request_otp()/enroll_by_aadhaar() (server/abha.py's _post(), which
    re-raises after call_with_retry exhausts its retries) propagated
    all the way up to cli.py's generic top-level catch-all, which just
    prints "<flow> raised an unexpected error: ConnectionError: ...".
    That's not wrong, but it says nothing about the one thing that
    actually matters here: unlike a response WE received (handled by
    report_failure() above), there is no way to know from a connection
    exception alone whether ABDM ever received and processed the
    request before the exception happened locally -- see
    server/abha.py's _post() docstring, "IDEMPOTENCY (unconfirmed...)"
    section, for the exact ambiguity this covers (a timed-out request
    that actually succeeded server-side, then gets silently treated as
    a normal retry-from-scratch). This says that explicitly instead of
    letting the generic message imply "nothing happened, safe to retry
    fresh."
    """
    print_failure(f"{context}: {type(exc).__name__}: {exc}")
    print_info("This was a connection-level failure (timeout / DNS / connection refused) -- not a response FROM ABDM.")
    print_info("Whether ABDM already received and processed this request before the failure happened locally is NOT known from here.")
    print_info("Do not assume it's safe to just retry with a fresh attempt -- verify the outcome first (e.g. check whether the ABHA account/session now exists) before retrying.")


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
