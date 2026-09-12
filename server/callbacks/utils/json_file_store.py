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
import threading
from collections import defaultdict
from pathlib import Path

# server/callbacks/utils/json_file_store.py -> parents[3] is the repo
# root, same depth convention used elsewhere in this codebase (e.g.
# tools/m2_test_suite/common.py resolving to the repo root).
_STORAGE_ROOT = Path(__file__).resolve().parents[3] / "storage"

# Per-file in-process write lock (edge-case-review pass, tracker case
# M2-1): this module's docstring already documents that append-only
# writes are "much less likely to clobber a concurrent writer than
# read-modify-write" but explicitly stops short of a real guarantee,
# since a bare `open(path, "a")` gives no atomicity promise for writes
# larger than the OS pipe buffer (a large consent notification's JSON
# line can easily exceed that) -- two genuinely simultaneous appends
# could still interleave their bytes at the OS level, corrupting both
# lines. A `threading.Lock` per file name serializes every _append()
# call FROM THIS PROCESS, which is the case that actually matters here:
# this server runs as one `uvicorn --reload` process handling every
# request (including two large consent-notify POSTs arriving "at the
# exact same time"), each request handled on its own thread via
# asyncio.to_thread() for the blocking file write. This does NOT
# extend to two truly separate OS processes writing the same file
# (e.g. a second server instance) -- that remains the documented,
# unchanged "not database-grade" limitation the module docstring
# already calls out; a real fix for that is still Redis/Postgres.
_locks_guard = threading.Lock()
_file_locks = defaultdict(threading.Lock)


def _lock_for(file_name):
    # The dict itself is mutated from multiple threads (first touch of
    # a given file_name), so guard the defaultdict's own insertion with
    # a small top-level lock -- cheap, and avoids two threads racing to
    # create two different Lock objects for the same file_name.
    with _locks_guard:
        return _file_locks[file_name]


# Per-file in-process incremental replay cache (tracker case M2-3): see
# _replay()'s own docstring below for why this exists. Guarded by the
# same per-file lock _append() already uses (_lock_for()), so a replay
# can never race a concurrent write to the same file.
_replay_cache = {}  # file_name -> {"state": dict, "offset": int}


def _replay(file_name):
    """
    Reads the log and replays it into the current state: the latest
    line for a key wins, and a delete tombstone removes the key from
    the result (even if an older "set" line for it exists earlier in
    the file).

    Corrupt/partially-written individual lines (e.g. a crash mid-append)
    are skipped rather than failing the whole read -- losing one record
    this way is an acceptable, already-established limitation (same
    category as the old version's "lost on restart" gap), not a new
    risk introduced here.

    PERFORMANCE (tracker case M2-3, found via a timing script against a
    generated tens-of-thousands-of-entries consents.jsonl): this used
    to re-read and re-parse EVERY line in the file from byte 0 on
    EVERY call -- O(file size) per lookup, forever, even for a
    get_key() of one key that hasn't changed in months. Since this
    store is append-only by design (see module docstring) and never
    compacts, a long-running server's storage file only grows, so that
    cost was unbounded and strictly worsening over the server's
    lifetime -- exactly the "does it slow down as the file grows"
    question M2-3 asks.

    FIX: cache the replayed state per file_name IN THIS PROCESS,
    remembering how many bytes of the file were already folded into
    it. A later call only reads and replays the NEW bytes appended
    since then (raw binary seek/tell -- exact byte offsets, no text-mode
    decode-cookie ambiguity), turning repeat-read cost into O(bytes
    appended since the last read) instead of O(total file size). The
    common case (many get_key() calls between occasional
    set_key()/delete_key() calls) gets dramatically cheaper; the worst
    case (every call preceded by a write) is no worse than before.

    Correctness: safe against this module's own write path specifically
    BECAUSE it's append-only (_append() only ever adds bytes at the
    end, under the same per-file lock this function now also takes --
    see _lock_for() -- so a cached prefix is never invalidated by a
    later write, only extended, and never read mid-write). NOT safe
    against something truncating/rewriting the file out from under this
    process (nothing in this codebase does that -- guarded anyway below
    via the size-shrank fallback), and NOT shared across OS processes --
    each process keeps its own cache, same "not database-grade, good
    enough for a couple of testers" scope the rest of this module's
    docstring already establishes.

    Returns:
        dict: {key: value} for every key whose latest line was a set,
            not a delete.
    """
    path = _STORAGE_ROOT / file_name
    if not path.exists():
        _replay_cache.pop(file_name, None)
        return {}

    with _lock_for(file_name):
        cached = _replay_cache.get(file_name)
        # IMPORTANT: reuse the SAME dict object already sitting in the
        # cache (mutate it in place below) rather than `dict(cached
        # ["state"])`-copying it here on every call. Copying an
        # n-key dict is itself O(n) -- doing that unconditionally, even
        # when there's nothing new to read, would silently defeat the
        # entire point of this cache (a hot get_key() loop would still
        # pay O(file size) per call, just via a dict-copy instead of a
        # file-read). Safe to mutate in place: this dict is never handed
        # to code outside this module -- get_key()/delete_key() only
        # ever read from _replay()'s return value, and get_all() (the
        # one caller that hands a dict to external code) copies it
        # before returning, below.
        state = cached["state"] if cached else {}
        offset = cached["offset"] if cached else 0

        size = path.stat().st_size
        if size < offset:
            # File shrank/was replaced out from under us (shouldn't
            # happen given this module's own append-only write path) --
            # don't silently serve stale/wrong data, fall back to a
            # full re-read from scratch.
            state = {}
            offset = 0

        if size > offset:
            with open(path, "rb") as f:
                f.seek(offset)
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        continue

                    key = record.get("key")
                    if key is None:
                        continue

                    if record.get("deleted"):
                        state.pop(key, None)
                    else:
                        state[key] = record.get("value")
                offset = f.tell()

        _replay_cache[file_name] = {"state": state, "offset": offset}
        # Returns the ACTUAL cached dict, not a copy (added alongside the
        # caching fix above -- returning `dict(state)` here, as the old
        # per-call-fresh-dict version safely could, would silently defeat
        # the whole point of caching: building a fresh len(state)-sized
        # dict copy on every single call is itself O(n), so a hot
        # get_key() loop against a large file would still cost O(file
        # size) per call even with zero new lines to read. Callers below
        # (get_key/delete_key's membership check) only ever read from
        # this, never mutate it. get_all() -- the one caller that hands
        # this dict to code outside this module, which might reasonably
        # mutate what it gets back -- copies it before returning, same
        # as its previous contract.
        return state


def _ends_with_newline_or_empty(path):
    """
    True if the file doesn't exist yet, is empty, or its last byte is
    already a newline. Used by _append() below (tracker case M2-14) to
    detect a stale, no-trailing-newline partial line left behind by a
    crash mid-write -- see that function's own comment for why this
    matters.
    """
    if not path.exists():
        return True
    size = path.stat().st_size
    if size == 0:
        return True
    with open(path, "rb") as f:
        f.seek(-1, 2)
        return f.read(1) == b"\n"


def _append(file_name, record):
    _STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    path = _STORAGE_ROOT / file_name
    # See _lock_for()'s own comment above -- serializes concurrent
    # writers to this same file from within this one process.
    with _lock_for(file_name):
        # M2-14 HARDENING (found via notebook-based real-code testing,
        # 2026-08-14 -- this case was previously marked "no fix needed,
        # the append-only design already handles it," but that assumed a
        # crash mid-write always leaves a trailing newline after the
        # partial content, so a later append could never land on the
        # same physical line as it). That assumption doesn't hold: a
        # single f.write(json.dumps(record) + "\n") call interrupted
        # before the trailing "\n" reaches disk leaves a partial line
        # with NO trailing newline. Without this guard, the next
        # _append() call (e.g. the server's first write after
        # restarting) would land directly after that stale partial
        # content with nothing separating them -- silently concatenating
        # the new, otherwise-perfectly-good record onto the tail of the
        # old corrupt line, so _replay()'s per-line json.loads() fails on
        # BOTH and the fresh record is lost too, not just the crashed
        # one. Ensuring the file always ends in a newline before writing
        # isolates any stale partial line onto its own (still skipped,
        # but harmless) line, so a fresh write is never dragged into it.
        needs_leading_newline = not _ends_with_newline_or_empty(path)
        with open(path, "a", encoding="utf-8") as f:
            if needs_leading_newline:
                f.write("\n")
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
    stored, not just one key. Returns a COPY of the cached state (see
    _replay()'s own comment on its return value) -- callers of get_all()
    are outside this module and might reasonably mutate what they get
    back; that must never corrupt the shared, cached state other calls
    rely on."""
    return dict(_replay(file_name))
