"""
Checkpoint tracker for edge-case test verification (EDGE_CASE_TEST_PLAN.md).

Purpose: when Aayush or a teammate runs test cases, this lets us scan only
the NEW content in capture/log files since the last time we looked --
instead of re-reading everything from scratch each session.

Hard rule this file exists to honor: we NEVER delete, truncate, or rewrite
anything under storage/ or logs/ (real ABDM sandbox consent data was
permanently lost that way once already). This module only ever *reads*
those files. All state it tracks lives in its own checkpoint file, which
sits outside storage/ and outside any *_test_suite/logs/ directory, so it
is always safe to freely edit or delete.

In scope for scanning (test-run evidence):
  - storage/api_capture.jsonl                  (legacy single capture log)
  - storage/api_capture/m2_*.jsonl, m3_*.jsonl  (per-module capture logs;
                                                   note: no m1_*.jsonl exists
                                                   yet as of 2026-08-12 --
                                                   M1 isn't in this dir)
  - storage/callbacks/*.json                    (one file per inbound
                                                   callback; tracked by
                                                   filename, not line offset)
  - tools/m1_test_suite/logs/run_*.log
  - tools/m2_test_suite/logs/run_*.log
  - tools/m3_test_suite/logs/run_*.log

Explicitly OUT of scope (live application state, not test-run evidence --
never scan these as if they were logs, and never touch them at all):
  - storage/consents.jsonl
  - storage/hiu_consents.jsonl
  - storage/hiu_health_information.jsonl
  - storage/link_sessions.jsonl
  - storage/patient_identities.jsonl
  - storage/pending_*.jsonl / storage/pending_*.json
"""
import json
import os

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".checkpoint_state.json")


def _load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)


def new_lines_since_checkpoint(filepath):
    """Return (new_lines, total_line_count) for a .jsonl/.log file.

    Only ever OPENS filepath for reading -- never writes, truncates, or
    deletes it. Call mark_processed() afterwards, once the new lines have
    actually been reviewed, to advance the checkpoint.
    """
    state = _load_state()
    key = os.path.abspath(filepath)
    last_line = state.get(key, {}).get("last_line", 0)
    if not os.path.exists(filepath):
        return [], last_line
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()
    return all_lines[last_line:], len(all_lines)


def mark_processed(filepath, line_count):
    """Advance the checkpoint for filepath to line_count lines processed."""
    state = _load_state()
    key = os.path.abspath(filepath)
    state[key] = {"last_line": line_count}
    _save_state(state)


def new_callback_files_since_checkpoint(callbacks_dir):
    """storage/callbacks/ has one file per callback (not line-based) --
    track which filenames have already been reviewed instead."""
    state = _load_state()
    seen = set(state.get("_callbacks_seen", []))
    if not os.path.isdir(callbacks_dir):
        return []
    return sorted(f for f in os.listdir(callbacks_dir) if f not in seen)


def mark_callbacks_processed(filenames):
    state = _load_state()
    seen = set(state.get("_callbacks_seen", []))
    seen.update(filenames)
    state["_callbacks_seen"] = sorted(seen)
    _save_state(state)
