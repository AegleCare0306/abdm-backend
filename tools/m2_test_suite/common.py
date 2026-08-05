"""
Shared helpers for the M2 test CLI's flow modules.

Every flow needs the same handful of things -- prompting for raw input,
sourcing patient/facility data from the repo's dummy CSVs (never
free-typed), polling for async callbacks, and printing results
consistently -- so those live here once instead of being copy-pasted into
every flow module. Flow modules stay focused on their own API sequence.

This is a separate package from tools/m1_test_suite/ (M1's common.py is
not imported here) since M2's flows have different data-sourcing needs
(facility/patient CSVs, async callback polling) that M1 never needed.
"""

import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from server.callbacks.repository.patient_repository import search_patient

# tools/m2_test_suite/common.py -> parents[2] is the repo root. Resolved
# once here so every path below is anchored to the repo root regardless
# of the CLI's/server's actual working directory.
_REPO_ROOT = Path(__file__).resolve().parents[2]

ORGANIZATIONS_CSV = _REPO_ROOT / "server" / "data" / "master" / "organizations.csv"
PATIENTS_CSV = _REPO_ROOT / "server" / "data" / "master" / "patients.csv"
CAPTURE_FILE = _REPO_ROOT / "storage" / "api_capture.jsonl"

_LOG_DIR = Path(__file__).resolve().parent / "logs"
# One file per CLI process run (fixed at import time), not one per call --
# every log_response() call during this run appends to the same file.
_RUN_LOG_FILE = _LOG_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


# -----------------------------------------------------------------------------
# Prompt / print helpers (same style as tools/m1_test_suite/common.py)
# -----------------------------------------------------------------------------

def prompt(label):
    """Prompts for one line of raw input, stripped."""
    return input(f"{label}: ").strip()


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


def print_response_body(response):
    """
    Neutral status/body dump for a call that already succeeded -- no
    pass/fail framing. Use this instead of server.utils.print_api_response()
    when you just want to show the raw response after confirming success
    yourself; print_api_response() always prints a hardcoded "ABDM API
    ERROR" header, which the rest of the codebase (M1's CLI, every M2
    callback service) deliberately calls only on the real failure path.
    Calling it unconditionally on a 200 (as earlier versions of a few M2
    CLI flows did) makes a correct response look like an error.
    """
    print("\nBody:")
    try:
        print(json.dumps(response.json(), indent=4))
    except ValueError:
        print(response.text)


def log_response(context, body):
    """
    Appends a full response/callback body to this process run's log file
    under tools/m2_test_suite/logs/, instead of printing it to the
    console. Console output stays limited to the friendly summary lines
    (print_success()/print_info()/etc.) -- this is where the ground truth
    goes so nothing is silently lost.

    SENSITIVE: these log files can contain ABHA addresses/numbers, link
    tokens, and mobile numbers in plaintext. This directory is gitignored
    (same *.log pattern as tools/m1_test_suite/logs/) -- never paste its
    contents anywhere; treat it as sensitive local-only debug output.
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "context": context,
        "body": body,
    }

    with open(_RUN_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, indent=2, default=str) + "\n")


# -----------------------------------------------------------------------------
# CSV-backed data selection -- never free-type patient/facility details
# -----------------------------------------------------------------------------

def select_facility():
    """
    Reads server/data/master/organizations.csv, prints a numbered list,
    and prompts for a selection.

    Unlike M1's select_account() (which auto-selects when there's only
    one entry), this always shows the list -- there are always 4
    facilities here, and seeing the choice matters.

    Returns:
        dict: The selected CSV row (hip_id, organization_name,
            organization_type, address_line1, city, state, pincode,
            phone, email).
    """
    with open(ORGANIZATIONS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print_info(f"{len(rows)} facilit{'y' if len(rows) == 1 else 'ies'} available:")
    for i, row in enumerate(rows, start=1):
        print_info(f"  [{i}] {row['hip_id']}  |  {row['organization_name']}  |  {row['city']}")

    while True:
        choice = prompt(f"Select a facility (1-{len(rows)})")
        if choice.isdigit() and 1 <= int(choice) <= len(rows):
            return rows[int(choice) - 1]
        print_info("Invalid choice, try again.")


def _extract_year(date_str):
    """
    Extracts the 4-digit year from a date_of_birth string, tolerant of
    either YYYY-MM-DD (the dummy generator's format, e.g. "1977-11-16")
    or DD-MM-YYYY (the format patients.csv's real rows -- PAT9001-PAT9004
    -- were hand-entered in, e.g. "20-10-1997") -- whichever dash-
    separated segment is 4 digits is taken as the year. Returns None for
    a blank/missing value or a string with no 4-digit segment, rather
    than raising.
    """
    if not date_str:
        return None
    for part in date_str.split("-"):
        if len(part) == 4 and part.isdigit():
            return int(part)
    return None


def select_patient(require_demographics=True):
    """
    Reads server/data/master/patients.csv, prints a numbered list, and
    prompts for a selection.

    Args:
        require_demographics (bool): If True (default), filters out rows
            with a blank gender or date_of_birth -- needed for flows that
            send those fields to ABDM (e.g. Link Token Generation). If
            False, every row is shown, including the 4 real ABHA-linked
            patients from actual M1 enrollments (PAT9001-PAT9004:
            Aayush Chordia, Manya Shah, Priya Shah, Pooja Anchaliya) whose
            gender/date_of_birth were never captured back into this CSV --
            those were previously invisible to every flow, even ones like
            Notify Care Context Update and SMS Notification that never
            touch gender/date_of_birth at all. Pass False for any flow
            that doesn't send demographic fields.

    Returns:
        dict: {patient_reference, abha_address, abha_number, name,
            gender, year_of_birth (int, or None if date_of_birth is
            blank), mobile}.
    """
    with open(PATIENTS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if require_demographics:
        rows = [row for row in rows if row.get("gender") and row.get("date_of_birth")]
        print_info(f"{len(rows)} patient(s) available (rows missing gender/date_of_birth filtered out -- required for this flow):")
    else:
        print_info(f"{len(rows)} patient(s) available:")

    for i, row in enumerate(rows, start=1):
        demo = f"{row['gender']}  |  {row['date_of_birth']}" if row.get("gender") and row.get("date_of_birth") else "(no gender/DOB on file)"
        print_info(f"  [{i}] {row['full_name']}  |  {row['abha_address']}  |  {demo}")

    while True:
        choice = prompt(f"Select a patient (1-{len(rows)})")
        if choice.isdigit() and 1 <= int(choice) <= len(rows):
            row = rows[int(choice) - 1]
            return {
                "patient_reference": row["patient_reference"],
                "abha_address": row["abha_address"],
                "abha_number": row["abha_number"],
                "name": row["full_name"],
                "gender": row["gender"] or None,
                "year_of_birth": _extract_year(row.get("date_of_birth")),
                "mobile": row["mobile"],
            }
        print_info("Invalid choice, try again.")


def select_care_contexts(abha_address, hip_id=None, single=False, multi_select=False):
    """
    Looks up care-context-level records for a patient via the same
    search_patient() production code uses, prints a numbered list, and
    returns either:
      - the full raw list, unprompted (single=False, multi_select=False --
        the original default, still used wherever "just give me
        everything" is correct, e.g. build_patient_payload() callers
        that don't need user choice),
      - exactly one record via a single-number prompt (single=True), or
      - a user-chosen subset via a comma-separated prompt, or "all"
        (multi_select=True) -- added 2026-08-04 so HIP-Initiated Linking
        callers aren't forced to link every care context record found;
        previously build_patient_payload() was always fed the entire
        list with no way to link a subset.

    single and multi_select are mutually exclusive; single wins if both
    are somehow passed True.

    Args:
        abha_address (str): Patient's ABHA address.
        hip_id (str, optional): Restrict to records at this facility.
        single (bool): If True, prompt for and return exactly one
            record.
        multi_select (bool): If True (and single is False), prompt for
            a comma-separated subset (or "all") and return just those
            records.
    Returns:
        list | dict | None: The raw record list, a chosen subset list,
            a single record dict, or None if single=True and no records
            were found.
    """
    records = search_patient(abha_address=abha_address, hip_id=hip_id)

    if not records:
        print_failure(f"No care context records found for {abha_address}" + (f" at facility {hip_id}" if hip_id else "") + ".")
        return None if single else []

    print_info(f"{len(records)} care context record(s) found:")
    for i, record in enumerate(records, start=1):
        print_info(f"  [{i}] {record['care_context_reference']}  |  {record['care_context_display']}  |  {record['hi_type']}")

    if single:
        while True:
            choice = prompt(f"Select one care context (1-{len(records)})")
            if choice.isdigit() and 1 <= int(choice) <= len(records):
                return records[int(choice) - 1]
            print_info("Invalid choice, try again.")

    if multi_select:
        while True:
            choice = prompt(f"Select care contexts to link (comma-separated, e.g. 1,3) or 'all' (1-{len(records)})")
            stripped = choice.strip().lower()
            if stripped == "all":
                return records
            parts = [p.strip() for p in choice.split(",") if p.strip()]
            if parts and all(p.isdigit() and 1 <= int(p) <= len(records) for p in parts):
                indices = sorted(set(int(p) for p in parts))
                selected = [records[i - 1] for i in indices]
                print_info(f"Selected {len(selected)} of {len(records)} record(s).")
                return selected
            print_info("Invalid choice, try again (e.g. '1,3' or 'all').")

    return records


# -----------------------------------------------------------------------------
# Local server / async callback helpers
# -----------------------------------------------------------------------------

def check_server_running(base_url="http://127.0.0.1:8000"):
    """
    Checks whether the local FastAPI server is up by hitting its /health
    endpoint. Connection errors (server not running) are treated as a
    plain False, not a crash.

    Returns:
        bool
    """
    try:
        response = requests.get(f"{base_url}/health", timeout=3)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def wait_for_callback(callback_type, since, timeout=90, poll_interval=2):
    """
    Polls storage/api_capture.jsonl for a fresh incoming callback matching
    callback_type, appearing after `since` (a timezone-aware datetime).
    Matches the exact "label" values used in server/callbacks/dispatcher.py's
    handlers dict (e.g. "generate_token", "care_context_link",
    "care_context_notify", "sms_notify") -- dispatch_callback() records
    every incoming callback via record_call(label=callback_type,
    direction="incoming", ...), so label IS the callback_type string.

    On timeout (returns None), the caller should check: is the server
    running? Is the ngrok tunnel up? Did ABDM actually receive the
    original outbound call?

    Returns:
        dict | None: The matching api_capture.jsonl entry, or None on
            timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if CAPTURE_FILE.exists():
            with open(CAPTURE_FILE, encoding="utf-8") as f:
                lines = f.readlines()
            for line in reversed(lines):
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get("label") != callback_type:
                    continue
                if entry.get("direction") != "incoming":
                    continue
                entry_time = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
                if entry_time > since:
                    return entry
        time.sleep(poll_interval)
    return None
