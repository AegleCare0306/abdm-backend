"""
One-time diagnostic capture of every incoming callback and outgoing API
call's full request/response detail, to storage/api_capture.jsonl.

Temporary: wired in to gather ground-truth ABDM sandbox payloads for
documentation and to resolve a couple of unconfirmed field shapes. This
module (and its call sites) is meant to be removed once that's done.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from server.callbacks.utils.flow_logger import log_error

CAPTURE_FILE = Path("storage/api_capture.jsonl")

CAPTURE_FILE.parent.mkdir(parents=True, exist_ok=True)


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
):
    """
    Appends one JSON line describing a single API call (an incoming ABDM
    callback, or an outgoing call to ABDM/an HIU) to storage/api_capture.jsonl.

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
        }

        with open(CAPTURE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    except Exception as exc:
        log_error(f"api_capture record_call failed for label={label}: {exc}")
