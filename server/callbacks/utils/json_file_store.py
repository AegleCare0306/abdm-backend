"""
Tiny helper for reading/writing a JSON-object-keyed dict to a file under
storage/, so state can be shared across separate OS processes.

WHY THIS EXISTS (real bug found 2026-08-04): server/callbacks/repository/
link_token_repository.py and patient_link_token_repository.py originally
used a plain module-level dict as their store. That works fine when the
writer and reader are the same process -- but the M2 test CLI
(tools/m2_test_suite/cli.py) runs as its OWN separate `python
tools/m2_test_suite/cli.py` process and imports server.hip_linking's
generate_link_token() directly, calling it in-process. That function
stashed the pending session in the CLI's own copy of the in-memory dict
-- invisible to the actually-running `uvicorn server.main:app` process,
which is what receives ABDM's on-generate-token callback. Result: the
callback handler's `get_pending_link_token()` lookup always failed
("No pending link token request found"), 100% of the time, for every
Flow 5 test run -- not a race condition or a reload artifact, a genuine
cross-process visibility gap. Confirmed via server logs showing the
lookup failing despite the CLI having just logged a successful save with
the exact same, correctly-correlated requestId moments earlier.

This file-backed store fixes that: both the CLI process and the server
process read/write the same file on disk, so whichever process performs
the save, the other can see it.

CONCURRENCY: uses a simple read-modify-write pattern, not a proper lock
file or database transaction. Fine for this project's actual usage (one
CLI process making one call at a time, one server process), not
appropriate for genuine concurrent writers. If that ever becomes a real
need, this is exactly the kind of gap the existing repository docstrings
already flag under "Future Implementation: Redis / PostgreSQL /
MongoDB".
"""

import json
from pathlib import Path

# server/callbacks/utils/json_file_store.py -> parents[3] is the repo
# root, same depth convention used elsewhere in this codebase (e.g.
# tools/m2_test_suite/common.py resolving to the repo root).
_STORAGE_ROOT = Path(__file__).resolve().parents[3] / "storage"


def _read(file_name):
    path = _STORAGE_ROOT / file_name
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        # Corrupt/partially-written file (e.g. a crash mid-write) -- treat
        # as empty rather than crashing every caller. Losing pending
        # sessions this way is an acceptable, already-established
        # limitation (same category as the prior in-memory store's
        # "lost on restart" gap), not a new risk introduced here.
        return {}


def _write(file_name, data):
    _STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    path = _STORAGE_ROOT / file_name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def set_key(file_name, key, value):
    """Reads the file, sets one key, writes it back."""
    data = _read(file_name)
    data[key] = value
    _write(file_name, data)


def get_key(file_name, key):
    """Reads the file, returns the value for one key (or None)."""
    return _read(file_name).get(key)


def delete_key(file_name, key):
    """Reads the file, deletes one key if present, writes back. Returns
    True if the key existed and was deleted, False otherwise."""
    data = _read(file_name)
    if key in data:
        del data[key]
        _write(file_name, data)
        return True
    return False
