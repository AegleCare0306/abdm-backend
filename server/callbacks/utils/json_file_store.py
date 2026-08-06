"""
Append-only, log-structured key-value store for sharing small pieces of
session state across OS processes (and, as of 2026-08-05, meant to
tolerate light concurrent access from a couple of testers hitting the
same server at once -- see below).

DESIGN (changed 2026-08-05, was read-modify-write): every write
(set_key or delete_key) APPENDS one JSON line to the file -- it never
reads the file, edits it in memory, and writes the whole thing back.
Reading (get_key/get_all) scans every line in the file, in order, and
replays it: each key's value is whatever its most recent line said,
and a delete is just a later line marking that key deleted (a
"tombstone"), not an actual line removal.

WHY: the old read-modify-write version had a real, documented race --
two callers writing at nearly the same moment could both read the same
starting state, and whichever one wrote last would silently overwrite
the other's change, since neither of them ever saw the other's write.
That's fine for one person testing serially, which is all this project
needed until now. It stops being fine the moment two people (or two
requests) can genuinely write to the same file around the same time --
raised 2026-08-05 while discussing how a production version of this
would need to handle real concurrency (answer: a real datastore like
Redis/Postgres, already noted in every repository module's "Future
Implementation" section).

This append-only version is a deliberate MIDDLE GROUND, not that real
fix: appending a single line is much less likely to clobber a
concurrent writer than read-modify-write is (each writer only ever adds
to the file, never reads-then-overwrites the whole thing), which is
enough to let a couple of people test concurrently without one
person's write silently erasing the other's. It is NOT a database-grade
guarantee -- Python's `open(path, "a")` does not provide an atomic,
cross-process write lock, so two truly simultaneous appends could in
rare cases still interleave badly at the OS level. Treat this as
"good enough for a couple of testers," not "production-safe under real
load" -- that's still Redis/Postgres, unchanged from before.

Every store file using this module is a `.jsonl` file (one JSON object
per line: `{"key": ..., "value": ..., "deleted": bool}`), not a single
JSON object like the old version.
"""

import json
from pathlib import Path

# server/callbacks/utils/json_file_store.py -> parents[3] is the repo
# root, same depth convention used elsewhere in this codebase (e.g.
# tools/m2_test_suite/common.py resolving to the repo root).
_STORAGE_ROOT = Path(__file__).resolve().parents[3] / "storage"


def _replay(file_name):
    """
    Reads every line of the log and replays it into the current state:
    the latest line for a key wins, and a delete tombstone removes the
    key from the result (even if an older "set" line for it exists
    earlier in the file).

    Corrupt/partially-written individual lines (e.g. a crash mid-append)
    are skipped rather than failing the whole read -- losing one record
    this way is an acceptable, already-established limitation (same
    category as the old version's "lost on restart" gap), not a new
    risk introduced here.

    Returns:
        dict: {key: value} for every key whose latest line was a set,
            not a delete.
    """
    path = _STORAGE_ROOT / file_name
    if not path.exists():
        return {}

    state = {}

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue

            key = record.get("key")
            if key is None:
                continue

            if record.get("deleted"):
                state.pop(key, None)
            else:
                state[key] = record.get("value")

    return state


def _append(file_name, record):
    _STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    path = _STORAGE_ROOT / file_name
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def set_key(file_name, key, value):
    """Appends a line recording this key's new value -- never edits or
    removes any earlier line."""
    _append(file_name, {"key": key, "value": value, "deleted": False})


def get_key(file_name, key):
    """Replays the log and returns the current value for one key (or
    None if it was never set, or its latest line was a delete)."""
    return _replay(file_name).get(key)


def delete_key(file_name, key):
    """Appends a tombstone line for this key. Returns True if the key
    had a current value immediately before this call, False otherwise
    -- matches the old version's return contract even though nothing is
    actually removed from the file."""
    existed = key in _replay(file_name)
    _append(file_name, {"key": key, "value": None, "deleted": True})
    return existed


def get_all(file_name):
    """Replays the log and returns every key's current value -- e.g.
    for a debugging helper that wants to see everything currently
    stored, not just one key."""
    return _replay(file_name)
