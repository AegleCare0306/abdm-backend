"""
Reusable test harness for exercising real Aegle Care EMR service functions
in isolation, without touching the running server, real ABDM, or anything
under storage/ or logs/.

WHY THIS EXISTS (Aayush, 2026-08-14): several edge cases in
EDGE_CASE_TEST_PLAN.md need a duplicate/corrupted/out-of-order callback
delivered to a real service function to prove a fix (e.g. an idempotency
guard) actually works. Doing that by hand -- replaying curl requests
against the live `uvicorn --reload` server -- means either editing
production code to force the scenario (risky, one-time, easy to forget to
revert) or hunting for a naturally-occurring duplicate in
storage/callbacks/. This harness instead imports the REAL service
functions directly (e.g. process_consent_notify) and calls them with
whatever payload/timing you want, in-process, entirely isolated:

  - Storage isolation: every repository in this codebase (consents, link
    sessions, pending requests, the idempotency guard itself, ...) is
    backed by server/callbacks/utils/json_file_store.py, which reads its
    storage root from one module-level variable (`_STORAGE_ROOT`).
    activate_scratch_storage() below points that variable at a fresh temp
    directory for the lifetime of the Python process running this
    notebook -- every read/write the real code does during your test
    lands there, NEVER in the repo's real storage/ directory. Nothing
    under storage/ or logs/ is ever touched by anything in this harness.
  - Network isolation: nothing here calls out to the real ABDM sandbox.
    Each notebook patches the specific outbound-call function(s) the
    service under test uses (e.g. send_on_consent_notify, request_otp)
    with a FakeResponse-returning stub via unittest.mock.patch, so you
    get a controllable, instant, offline stand-in instead of a real
    network call.
  - Code isolation: this harness never edits any file under server/ or
    tools/ -- it only imports and calls what's already there. Re-run the
    notebook any number of times; the original code is never modified.

VERIFIED (2026-08-14): every pattern in this file was smoke-tested end to
end against a copy of this repo's real service/repository code before
being handed to Aayush -- not just written from reading the source.

HOW TO ADD A NEW SET FOR A DIFFERENT CASE: import the real service module
(`import server.callbacks.services.<x>_service as svc`), call
activate_scratch_storage() once at the top of your notebook, patch
whatever outbound calls that service makes (see set_a_idempotency.ipynb
for worked examples against 4 different services), build a synthetic
`callback_data = {"headers": {...}, "body": {...}}` dict matching the
shape server/callbacks/dispatcher.py builds for a real inbound request
(headers is a plain dict, keys lowercase; body is whatever JSON ABDM
would POST), and call the service's process_*() coroutine directly via
`await svc.process_x(callback_data)` -- Jupyter supports top-level
`await` right inside a code cell, no asyncio.run() needed -- as many
times, with whatever mutated values, as the scenario needs. To find a
real payload shape to copy from, open a file under storage/callbacks/
(read-only) that matches the route you're testing.

NOTE ON asyncio.run() / the run() helper below: a Jupyter kernel already
has its own event loop running, so calling asyncio.run() inside a
notebook cell raises "asyncio.run() cannot be called from a running
event loop" -- use plain `await` in notebook cells instead (see
set_a_idempotency.ipynb for the pattern actually used). run() below is
kept only for the case where you copy one of these test bodies into a
plain .py script run outside Jupyter (e.g. `python3 my_test.py`), where
there's no event loop already running and asyncio.run() works fine.
"""

import asyncio
import tempfile
from pathlib import Path

import server.callbacks.utils.json_file_store as json_file_store


class FakeResponse:
    """Stand-in for a `requests` Response object -- everything in this
    codebase only ever reads .status_code, .json(), and (when patching
    below the record_call() layer -- i.e. patching requests.post/get
    itself rather than a call-site function) .headers off the real
    thing, so that's all this replicates. .headers defaults to {} (added
    2026-08-14 for the retry-logic notebooks, which patch requests.post/
    get directly so the real call-site function -- including its own
    record_call(..., response_headers=dict(response.headers), ...) --
    actually runs, unlike earlier notebooks that patch a whole call-site
    function and never reach that code)."""

    def __init__(self, status_code=200, body=None, headers=None, not_json=False, text=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = headers if headers is not None else {}
        # not_json=True (added 2026-08-15 for tracker case M1-5) makes
        # .json() raise ValueError like the real `requests` library does
        # for a genuinely non-JSON body (e.g. an HTML error page from a
        # misbehaving proxy in front of ABDM, on an otherwise-200
        # response) -- the default .json() behavior above can't simulate
        # this since it always has *some* dict to return.
        self._not_json = not_json
        self.text = text if text is not None else "<html>not json at all</html>"

    def json(self):
        if self._not_json:
            raise ValueError("No JSON object could be decoded (simulated malformed body)")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise __import__("requests").exceptions.HTTPError(f"{self.status_code} error", response=self)


class CallRecorder:
    """
    A callable stand-in for any outbound function this codebase calls
    (send_on_confirm, request_otp, notify_care_context_update, ...).
    Records every call's args/kwargs and returns a fixed (or per-call)
    FakeResponse, so a test can assert exactly how many times a
    side-effecting call happened -- which is the actual proof an
    idempotency fix works (or doesn't).

    Usage:
        recorder = CallRecorder(FakeResponse(202))
        with patch.object(some_service_module, "send_on_confirm", recorder):
            ...
        print(recorder.call_count)   # how many times it was actually called
        print(recorder.calls)        # the exact args/kwargs each time
    """

    def __init__(self, response=None, responses=None):
        self.calls = []
        self._response = response or FakeResponse(202)
        self._responses = responses  # optional list, one entry per call

    def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        if self._responses is not None:
            idx = min(len(self.calls) - 1, len(self._responses) - 1)
            return self._responses[idx]
        return self._response

    @property
    def call_count(self):
        return len(self.calls)


def activate_scratch_storage(label=""):
    """
    Points every repository's storage root at a brand-new, empty temp
    directory for the rest of this Python process -- call this ONCE per
    notebook kernel, near the top, before seeding any data or calling any
    service function. Returns the Path so you can inspect it (e.g.
    print((path / "consents.jsonl").read_text()) after a run) if you want
    to see exactly what the real code wrote, entirely separate from the
    repo's real storage/ directory.

    Safe to call again mid-notebook if you want a completely clean slate
    for a new scenario (e.g. to guarantee a request_id has never been
    seen before) -- each call gets its own fresh temp directory; the old
    one is simply abandoned (OS temp cleanup handles it eventually,
    nothing you need to clean up by hand).
    """
    scratch = Path(tempfile.mkdtemp(prefix=f"edge_case_scratch_{label}_"))
    json_file_store._STORAGE_ROOT = scratch
    print(f"[harness] scratch storage active at: {scratch}")
    print("[harness] (NOT the repo's real storage/ directory -- nothing here touches that)")
    return scratch


def run(coro):
    """Tiny asyncio.run() wrapper so notebook cells read a bit cleaner:
    run(svc.process_x(callback_data)) instead of asyncio.run(svc.process_x(callback_data))."""
    return asyncio.run(coro)


def check(label, condition):
    """Prints a clear PASS/FAIL line and returns the condition, so a cell
    can end with a readable summary instead of a bare assert traceback on
    failure. Use a plain `assert` instead if you want the cell to stop
    hard the moment something doesn't match."""
    print(f"{'PASS' if condition else 'FAIL'} -- {label}")
    return condition
