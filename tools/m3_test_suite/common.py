"""
Shared helpers for the M3 test CLI's flow modules.

Separate from tools/m2_test_suite/common.py -- kept self-contained the
same way m1_test_suite and m2_test_suite are separate from each other,
rather than importing across test-suite packages.
"""

import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

from server.callbacks.repository.hiu_consent_repository import get_all_hiu_consents

# tools/m3_test_suite/common.py -> parents[2] is the repo root. Resolved
# once here so every path below is anchored to the repo root regardless
# of the CLI's/server's actual working directory.
_REPO_ROOT = Path(__file__).resolve().parents[2]

ORGANIZATIONS_CSV = _REPO_ROOT / "server" / "data" / "master" / "organizations.csv"
PATIENTS_CSV = _REPO_ROOT / "server" / "data" / "master" / "patients.csv"
PRACTITIONERS_CSV = _REPO_ROOT / "server" / "data" / "master" / "practitioners.csv"
PRACTITIONER_ORGANIZATIONS_CSV = _REPO_ROOT / "server" / "data" / "master" / "practitioner_organizations.csv"

# CHANGED 2026-08-10: api_capture entries are split one file per category
# per day (server/callbacks/utils/api_capture.py) -- every M3
# callback_type wait_for_callback() below is ever called with is tagged
# category "m3" by dispatcher.py's own mapping, so this only needs this
# suite's own m3_*.jsonl files. Mirrors tools/m2_test_suite/common.py's
# own CAPTURE_DIR/wait_for_callback().
CAPTURE_DIR = _REPO_ROOT / "storage" / "api_capture"

if str(_REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "tools"))
from dummy_emr.hi_types import ALL_HI_TYPES

_LOG_DIR = Path(__file__).resolve().parent / "logs"
# One file per CLI process run (fixed at import time), not one per call --
# every log_response() call during this run appends to the same file.
_RUN_LOG_FILE = _LOG_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


# -----------------------------------------------------------------------------
# Prompt / print helpers (same style as tools/m2_test_suite/common.py)
# -----------------------------------------------------------------------------

def prompt(label):
    """Prompts for one line of raw input, stripped."""
    return input(f"{label}: ").strip()


def prompt_with_default(label, default):
    """Prompts for one line of raw input, falling back to `default` if
    left blank."""
    value = input(f"{label} [default: {default}]: ").strip()
    return value or default


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


def log_response(context, body):
    """
    Appends a full response/callback body to this process run's log file
    under tools/m3_test_suite/logs/, instead of printing it to the
    console.

    SENSITIVE: these log files can contain ABHA addresses and consent
    request context in plaintext. This directory is gitignored (same
    *.log pattern as the other test suites' logs directories) -- never
    paste its contents anywhere; treat it as sensitive local-only debug
    output.
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


def select_patient():
    """
    Reads server/data/master/patients.csv, prints a numbered list, and
    prompts for a selection.

    Returns:
        dict: {patient_reference, abha_address, abha_number, name,
            gender, mobile}.
    """
    with open(PATIENTS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print_info(f"{len(rows)} patient(s) available:")
    for i, row in enumerate(rows, start=1):
        print_info(f"  [{i}] {row['full_name']}  |  {row['abha_address']}")

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
                "mobile": row["mobile"],
            }
        print_info("Invalid choice, try again.")


def select_practitioner(hip_id):
    """
    Reads server/data/master/practitioner_organizations.csv filtered to
    active practitioners at `hip_id`, joins each to their record in
    server/data/master/practitioners.csv, prints a numbered list, and
    prompts for a selection.

    This is the requester (treating clinician) for a Consent Init
    Request -- their real registration identity, not something the
    doctor using the EMR should have to type by hand every time they
    request a patient's records.

    Args:
        hip_id (str): The facility's hip_id, from select_facility()'s
            returned row -- only practitioners linked to this facility
            (and marked active) are shown.

    Returns:
        dict: {practitioner_reference, full_name, registration_number,
            registration_system, speciality}.
    """
    with open(PRACTITIONER_ORGANIZATIONS_CSV, newline="", encoding="utf-8") as f:
        links = [
            row for row in csv.DictReader(f)
            if row["hip_id"] == hip_id and row["active"] == "True"
        ]

    with open(PRACTITIONERS_CSV, newline="", encoding="utf-8") as f:
        practitioner_by_ref = {row["practitioner_reference"]: row for row in csv.DictReader(f)}

    rows = [practitioner_by_ref[link["practitioner_reference"]] for link in links if link["practitioner_reference"] in practitioner_by_ref]

    if not rows:
        print_info(f"No active practitioners found for facility {hip_id} -- falling back to the full practitioner list.")
        with open(PRACTITIONERS_CSV, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

    print_info(f"{len(rows)} practitioner(s) available at this facility:")
    for i, row in enumerate(rows, start=1):
        print_info(f"  [{i}] {row['full_name']}  |  {row['speciality']}  |  {row['registration_number']} ({row['registration_system']})")

    while True:
        choice = prompt(f"Select the requesting practitioner (1-{len(rows)})")
        if choice.isdigit() and 1 <= int(choice) <= len(rows):
            row = rows[int(choice) - 1]
            return {
                "practitioner_reference": row["practitioner_reference"],
                "full_name": row["full_name"],
                "registration_number": row["registration_number"],
                "registration_system": row["registration_system"],
                "speciality": row["speciality"],
            }
        print_info("Invalid choice, try again.")


# -----------------------------------------------------------------------------
# Consent purpose selection -- text and code are two representations of the
# SAME fixed choice, not independent fields; asking for both separately lets
# them go out of sync. Confirmed from the M3 spec doc's own purpose table
# (Purpose of Use, a subset of HL7's v3-PurposeOfUse valueset) -- the table's
# own docx export merges the Display column across rows, but the code->text
# pairing below is unambiguous (each code is a standard abbreviation of
# exactly one display name in its row) and "Self Requested"/PATRQT is
# independently confirmed via a separate real captured example elsewhere in
# the same document.
# -----------------------------------------------------------------------------

PURPOSE_OPTIONS = [
    {"text": "Care Management", "code": "CAREMGT"},
    {"text": "Break the Glass", "code": "BTG"},
    {"text": "Public Health", "code": "PUBHLTH"},
    {"text": "Healthcare Payment", "code": "HPAYMT"},
    {"text": "Disease Specific Healthcare Research", "code": "DSRCH"},
    {"text": "Self Requested", "code": "PATRQT"},
]


def select_hi_types():
    """
    Prints the 8 ABDM Health Information Types (from
    tools/dummy_emr/hi_types.py's ALL_HI_TYPES -- confirmed against real
    ABDM sandbox data, see that module's docstring) as a numbered list and
    prompts for a multi-selection, same comma-separated-indices / 'all'
    UX as tools/m2_test_suite/common.py's select_care_contexts(multi_select=True).

    Returns:
        list[str]: The selected HI type strings, e.g.
            ["Prescription", "DiagnosticReport"].
    """
    hi_types = sorted(ALL_HI_TYPES)

    print_info(f"{len(hi_types)} HI type(s) available:")
    for i, hi_type in enumerate(hi_types, start=1):
        print_info(f"  [{i}] {hi_type}")

    while True:
        choice = prompt(f"Select HI types (comma-separated, e.g. 1,3) or 'all' (1-{len(hi_types)})")
        stripped = choice.strip().lower()
        if stripped == "all":
            return hi_types
        parts = [p.strip() for p in choice.split(",") if p.strip()]
        if parts and all(p.isdigit() and 1 <= int(p) <= len(hi_types) for p in parts):
            indices = sorted(set(int(p) for p in parts))
            selected = [hi_types[i - 1] for i in indices]
            print_info(f"Selected {len(selected)} of {len(hi_types)}: {', '.join(selected)}")
            return selected
        print_info("Invalid choice, try again (e.g. '1,3' or 'all').")


def select_purpose():
    """
    Prints the 6 confirmed ABDM consent purposes as a numbered list and
    prompts for a selection -- returns both `text` and `code` together so
    they can never be set to a mismatched pair.

    Returns:
        dict: {"text": str, "code": str}
    """
    print_info(f"{len(PURPOSE_OPTIONS)} purpose(s) available:")
    for i, option in enumerate(PURPOSE_OPTIONS, start=1):
        print_info(f"  [{i}] {option['text']}  ({option['code']})")

    while True:
        choice = prompt(f"Select a purpose (1-{len(PURPOSE_OPTIONS)})")
        if choice.isdigit() and 1 <= int(choice) <= len(PURPOSE_OPTIONS):
            return PURPOSE_OPTIONS[int(choice) - 1]
        print_info("Invalid choice, try again.")


def select_granted_consent():
    """
    Reads every stored HIU consent artefact
    (hiu_consent_repository.get_all_hiu_consents()), filters to status ==
    "GRANTED" (the only status Block 2 can act on -- a fetched consent
    can also be DENIED/REVOKED, which this excludes), then prompts in
    FOUR steps -- patient, then which HIU requested it, then which
    requesting DOCTOR (practitioner) it was requested under, then which
    facility (HIP) that request is for -- rather than one flat numbered
    list.

    CHANGED 2026-08-11 (two passes) + 2026-08-12 (this pass, adding the
    doctor step): originally a single flat list. First pass split it
    into patient -> consent (with HIU/HIP shown inline on each row).
    Second pass split the second level further into its own HIU step,
    then a facility step. This pass adds a third narrowing level between
    those two: consent_detail.requester ({name, identifier}) -- the
    treating practitioner the Consent Init Request was made under (see
    server/hiu_consent.py's initiate_consent_request(), which sends this
    from select_practitioner()'s choice) -- was already being captured
    and stored on every artefact, but was invisible in this picker.
    Confirmed via a real user question while testing (2026-08-12): with
    the same patient/HIU/facility combination requested by two different
    doctors on two different days (e.g. re-running Consent Init Request
    daily during testing), those consents showed up here as visually
    IDENTICAL rows with no way to tell them apart short of opening
    storage/hiu_consents.jsonl directly -- a real gap, not just cosmetic,
    since a real EMR absolutely needs "which of MY patient's consents is
    this" to be answerable by the requesting doctor, not just by facility.

    One requester currently applies to every facility resolved by a
    single Consent Init Request call (hiu_consent.py sends hip=None and
    ABDM resolves which HIP(s) hold the data; whichever practitioner was
    selected for that one call is the requester for all facilities ABDM
    returns under it) -- so narrowing by requester before facility is the
    correct order, not the other way around: it's the doctor's own
    request being followed up on, which then may cover multiple
    facilities.

    Used by the Health Information Request flow (M3 Block 2) to pick
    which already-fetched consent to request data for.

    Returns:
        dict | None: {"consent_id": str, "consent_detail": dict} for the
            selected consent, or None if no GRANTED consents are stored
            yet (nothing to select).
    """
    all_consents = get_all_hiu_consents()

    granted = [
        {
            "consent_id": consent_id,
            "consent_detail": data.get("consent_detail") or {},
            "patient_id": ((data.get("consent_detail") or {}).get("patient") or {}).get("id"),
            "hiu_id": ((data.get("consent_detail") or {}).get("hiu") or {}).get("id"),
            "hip_id": ((data.get("consent_detail") or {}).get("hip") or {}).get("id"),
            "hip_name": ((data.get("consent_detail") or {}).get("hip") or {}).get("name"),
            "requester_name": ((data.get("consent_detail") or {}).get("requester") or {}).get("name"),
            "requester_reg_no": (((data.get("consent_detail") or {}).get("requester") or {}).get("identifier") or {}).get("value"),
            "created_at": (data.get("consent_detail") or {}).get("createdAt"),
        }
        for consent_id, data in all_consents.items()
        if data.get("status") == "GRANTED"
    ]

    if not granted:
        print_info("No GRANTED consents stored yet -- run 'Consent Init Request' first and wait for the patient to grant it (Block 1).")
        return None

    # Step 1: pick a patient. Order preserved by first appearance rather
    # than sorted alphabetically, so it roughly tracks recency of
    # consent creation, same spirit as the rest of this module's lists.
    patient_ids = []
    for item in granted:
        if item["patient_id"] not in patient_ids:
            patient_ids.append(item["patient_id"])

    print_info(f"{len(patient_ids)} patient(s) with GRANTED consent(s):")
    for i, patient_id in enumerate(patient_ids, start=1):
        count = sum(1 for item in granted if item["patient_id"] == patient_id)
        print_info(f"  [{i}] {patient_id}  ({count} consent(s))")

    while True:
        choice = prompt(f"Select a patient (1-{len(patient_ids)})")
        if choice.isdigit() and 1 <= int(choice) <= len(patient_ids):
            selected_patient_id = patient_ids[int(choice) - 1]
            break
        print_info("Invalid choice, try again.")

    patient_subset = [item for item in granted if item["patient_id"] == selected_patient_id]

    # Step 2: within that patient, pick which HIU requested the data --
    # two different HIU identities can each hold their own separate
    # GRANTED consent for the very same patient, so this has to be its
    # own explicit step, not just a label on a combined row.
    hiu_ids = []
    for item in patient_subset:
        if item["hiu_id"] not in hiu_ids:
            hiu_ids.append(item["hiu_id"])

    print_info(f"{len(hiu_ids)} HIU(s) with GRANTED consent(s) for {selected_patient_id}:")
    for i, hiu_id in enumerate(hiu_ids, start=1):
        count = sum(1 for item in patient_subset if item["hiu_id"] == hiu_id)
        print_info(f"  [{i}] {hiu_id}  ({count} consent(s))")

    while True:
        choice = prompt(f"Select a requesting HIU (1-{len(hiu_ids)})")
        if choice.isdigit() and 1 <= int(choice) <= len(hiu_ids):
            selected_hiu_id = hiu_ids[int(choice) - 1]
            break
        print_info("Invalid choice, try again.")

    hiu_subset = [item for item in patient_subset if item["hiu_id"] == selected_hiu_id]

    # Step 3 (added 2026-08-12): within that patient + HIU, pick which
    # requesting doctor's consent this is -- see this function's own
    # docstring for why. Keyed on (name, reg_no) rather than name alone,
    # in case two practitioners ever share a display name. Order by most
    # recent createdAt first, since "which request was this" is usually
    # a recency question during testing (re-running Block 1 across
    # multiple days/practitioners, as happened here).
    requesters = []
    for item in hiu_subset:
        key = (item["requester_name"], item["requester_reg_no"])
        if key not in [r["key"] for r in requesters]:
            requesters.append({
                "key": key,
                "name": item["requester_name"],
                "reg_no": item["requester_reg_no"],
                "latest_created_at": item["created_at"],
            })
        else:
            existing = next(r for r in requesters if r["key"] == key)
            if (item["created_at"] or "") > (existing["latest_created_at"] or ""):
                existing["latest_created_at"] = item["created_at"]
    requesters.sort(key=lambda r: r["latest_created_at"] or "", reverse=True)

    if len(requesters) > 1:
        print_info(f"{len(requesters)} requesting doctor(s) with GRANTED consent(s) from HIU {selected_hiu_id} for {selected_patient_id}:")
        for i, r in enumerate(requesters, start=1):
            count = sum(1 for item in hiu_subset if (item["requester_name"], item["requester_reg_no"]) == r["key"])
            label = r["name"] or "(no requester name on file)"
            reg = f" ({r['reg_no']})" if r["reg_no"] else ""
            when = f" -- requested {r['latest_created_at']}" if r["latest_created_at"] else ""
            print_info(f"  [{i}] {label}{reg}  ({count} consent(s)){when}")

        while True:
            choice = prompt(f"Select a requesting doctor (1-{len(requesters)})")
            if choice.isdigit() and 1 <= int(choice) <= len(requesters):
                selected_requester_key = requesters[int(choice) - 1]["key"]
                break
            print_info("Invalid choice, try again.")

        requester_subset = [item for item in hiu_subset if (item["requester_name"], item["requester_reg_no"]) == selected_requester_key]
    else:
        # Only one requester on file for this patient+HIU -- nothing to
        # disambiguate, skip straight to the facility step (same
        # behavior as before this change for the common case).
        requester_subset = hiu_subset

    # Step 4: within that patient + HIU + requester, pick which facility
    # (HIP) holds the data -- shown by name, not just the raw hip_id,
    # since that's what's actually stored on the artefact
    # (consent_detail.hip.name) and what a real user would recognize.
    print_info(f"{len(requester_subset)} facilit{'y' if len(requester_subset) == 1 else 'ies'} granted for {selected_patient_id}:")
    for i, item in enumerate(requester_subset, start=1):
        print_info(f"  [{i}] {item['hip_name']} ({item['hip_id']})")

    while True:
        choice = prompt(f"Select a facility (1-{len(requester_subset)})")
        if choice.isdigit() and 1 <= int(choice) <= len(requester_subset):
            selected = requester_subset[int(choice) - 1]
            return {"consent_id": selected["consent_id"], "consent_detail": selected["consent_detail"]}
        print_info("Invalid choice, try again.")


# -----------------------------------------------------------------------------
# Local server helper
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


# -----------------------------------------------------------------------------
# Async callback polling
# -----------------------------------------------------------------------------

def wait_for_callback(callback_type, since, match_fn=None, timeout=90, poll_interval=2):
    """
    Polls storage/api_capture/m3_*.jsonl for a fresh incoming callback
    matching callback_type, appearing after `since` (a timezone-aware
    datetime). Mirrors tools/m2_test_suite/common.py's wait_for_callback()
    exactly, scoped to this suite's own m3_*.jsonl files -- every M3
    callback_type is tagged category "m3" by dispatcher.py's own mapping,
    so this only needs this suite's own m3_*.jsonl files.

    Matches the exact "label" values used in
    server/callbacks/dispatcher.py's handlers dict (e.g.
    "consent_hiu_on_init", "consent_hiu_notify", "consent_hiu_on_fetch",
    "health_information_hiu_on_request", "health_information_hiu_push")
    -- dispatch_callback() records every incoming callback via
    record_call(label=callback_type, direction="incoming", ...), so label
    IS the callback_type string.

    ADDED match_fn 2026-08-11: label + timestamp alone can't tell two
    concurrent Block 2 requests apart -- confirmed live to cause real
    failures once more than one Health Information Request is in flight
    close together (e.g. two HIU identities being tested side by side):
    without a way to pick out THIS call's own callback specifically,
    polling can return a different call's entry (wrong transactionId
    picked up silently) while the actual matching callback for this call
    never gets noticed at all (a false timeout, even though the server
    genuinely handled it -- visible in api_capture, just never picked up
    here). Callers should pass a callable that takes one api_capture
    entry dict and returns True only for the entry belonging to their own
    specific call (e.g. checking the echoed response.requestId or a
    transactionId), not just relying on label+time. Optional and
    defaults to None (matches anything of the right label/time, the
    original behaviour) so this stays a compatible extension, not a
    breaking change, for any future caller that only ever has one
    request in flight at a time.

    On timeout (returns None), the caller should check: is the server
    running? Is the ngrok tunnel up? Did ABDM actually receive the
    original outbound call? And, if match_fn was given: is it possible
    another concurrent request's callback is what's actually arriving
    (check the raw m3_*.jsonl file for entries of this label around the
    same time)?

    Returns:
        dict | None: The matching api_capture entry, or None on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if CAPTURE_DIR.exists():
            for capture_file in sorted(CAPTURE_DIR.glob("m3_*.jsonl")):
                with open(capture_file, encoding="utf-8") as f:
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
                    if entry_time <= since:
                        continue
                    if match_fn is not None and not match_fn(entry):
                        continue
                    return entry
        time.sleep(poll_interval)
    return None
