"""
One-time diagnostic capture of every incoming callback and outgoing API
call's full request/response detail, to
storage/api_capture/{category}_{date}.jsonl.

CHANGED 2026-08-10: was a single shared storage/api_capture.jsonl (1.4MB
and growing, with M1/M2/M3/shared-infra calls all interleaved with no way
to tell what produced a given line). That file is left in place,
untouched, as historical data already cited by filename in Notion
documentation -- new calls are no longer appended to it. Entries are now
split one file per category per day under storage/api_capture/, where
category comes from get_log_category() (server/callbacks/utils/
flow_logger.py's ContextVar) -- see that module's docstring for exactly
how a category gets set. A line's category is whichever flow triggered
the call, not which endpoint it hits.

Temporary: wired in to gather ground-truth ABDM sandbox payloads for
documentation and to resolve a couple of unconfirmed field shapes. This
module (and its call sites) is meant to be removed once that's done.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from server.callbacks.utils.flow_logger import log_error, get_log_category

# ANCHOR FIX (tracker case M2-34/M3-7): was a bare relative path,
# resolved against the process's current working directory at IMPORT
# time -- see storage.py's matching fix for the full rationale (this is
# the exact "M3 api-capture directory path is resolved relative to the
# launch directory" gap the original test plan flagged for M3-7).
# server/callbacks/utils/api_capture.py -> parents[3] is the repo root.
CAPTURE_DIR = Path(__file__).resolve().parents[3] / "storage" / "api_capture"

CAPTURE_DIR.mkdir(parents=True, exist_ok=True)


def record_call(
    label,
    direction,
    method,
    url,
    request_headers,
    request_body,
    response_status=None,
    response_headers=None,
    response_body=None,
    attachment_mechanisms=None,
):
    """
    Appends one JSON line describing a single API call (an incoming ABDM
    callback, or an outgoing call to ABDM/an HIU) to
    storage/api_capture/{category}_{date}.jsonl, where category is
    whichever flow triggered this call (get_log_category()) and date is
    today's local date.

    attachment_mechanisms (list[str] | None): which FHIR attachment
    mechanism(s) ("DocumentReference", "Binary", "Media") were present in
    the bundle(s) this call is pushing, if any -- lets these files be
    grepped/parsed later to correlate failures with a specific attachment
    mechanism. Only meaningful for the "data-push-to-hiu" call today (see
    server/healthinformation.py's send_health_information_data()); every
    other call site simply doesn't pass it, leaving it None.

    Never raises -- a capture failure must never break the real call it's
    observing, so all file-write logic is wrapped and swallowed here.
    """

    try:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "label": label,
            "direction": direction,
            "method": method,
            "url": url,
            "request_headers": request_headers,
            "request_body": request_body,
            "response_status": response_status,
            "response_headers": response_headers,
            "response_body": response_body,
            "attachment_mechanisms": attachment_mechanisms,
        }

        category = get_log_category()
        date_str = datetime.now().strftime("%Y-%m-%d")
        capture_file = CAPTURE_DIR / f"{category}_{date_str}.jsonl"

        with open(capture_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    except Exception as exc:
        log_error(f"api_capture record_call failed for label={label}: {exc}")
