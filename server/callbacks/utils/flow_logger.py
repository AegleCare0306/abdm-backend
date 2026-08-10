"""
Flow Logger.

Replaces scattered print() statements across the M2 callback services with
a consistent, narrative logging style -- each call describes what's
actually happening in plain language, not just a technical function name.

Writes to both the console (for live viewing while testing -- the combined,
all-categories view is still useful there, so this stays as one shared
StreamHandler) and a persistent log file per category per day
(logs/{category}_{date}.log -- CHANGED 2026-08-10, was a single shared
logs/flow.log; already covered by .gitignore's *.log pattern) so nothing
is lost between server restarts, and so a specific flow's log can be
opened directly instead of grepping one giant shared file. The old
logs/flow.log is left in place, untouched, as historical data -- new log
lines are written to the per-category-per-day files only. See
get_log_category()'s docstring below for how a line's category is
decided.
"""

import contextvars
import logging
from datetime import datetime
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_logger = logging.getLogger("abdm_flow")
_logger.setLevel(logging.INFO)


# Set once per incoming request (see dispatch_callback()) so every log call
# made anywhere downstream during that request's handling -- including deep
# inside the service functions, with no new parameter needed at any of their
# call sites -- can tag its lines with the same ID. A ContextVar (not a plain
# module-level global) is required here specifically because this is a
# FastAPI app handling requests via async def: a plain global would leak
# across concurrently-handled requests, where a ContextVar stays correctly
# scoped to the async task that set it.
_correlation_id: contextvars.ContextVar = contextvars.ContextVar("correlation_id", default=None)


def set_correlation_id(correlation_id):
    _correlation_id.set(correlation_id)


def get_correlation_id():
    return _correlation_id.get()


# Same ContextVar pattern as _correlation_id above, used to route each log
# line (and, via server/callbacks/utils/api_capture.py's own use of
# get_log_category(), each captured API call) to the right per-category
# file -- "m1"/"m2"/"m3" for the three ABDM milestones, or "server" for
# anything not attributable to one of them (the default below, and also
# what dispatch_callback() sets for a callback_type it doesn't recognize).
#
# A line's category is whichever FLOW triggered it, not which endpoint it
# hits -- set once per process by the M1/M2/M3 test CLIs' main() (each CLI
# is its own OS process making outbound calls directly, so the whole
# process shares one category), and once per incoming request by
# dispatch_callback() (the running server is one persistent process
# serving both M2's and M3's callbacks, so it re-tags per request instead).
# Everything downstream of that single tagging point -- including a shared
# helper like get_gateway_token(), or an outbound call made from inside a
# callback service like server/hiu_consent.py's fetch_consent() -- inherits
# the ambient category automatically, with no per-call-site change needed,
# exactly like _correlation_id above. Defaults to "server" if nothing ever
# sets it (e.g. server/main.py's generic /health and /echo endpoints), so
# there's always a file a line can go to.
_log_category: contextvars.ContextVar = contextvars.ContextVar("log_category", default="server")


def set_log_category(category):
    _log_category.set(category)


def get_log_category():
    return _log_category.get()


class _CategoryDatedFileHandler(logging.Handler):
    """
    Resolves logs/{category}_{date}.log fresh on every emit() call (today's
    local date, current ambient category from get_log_category()) instead
    of writing to one fixed file -- the category (and, at midnight, the
    date) can differ from one log call to the next within the same
    process, e.g. the server handling an M2 callback right after an M3
    one. Deliberately doesn't keep a file handle open across calls for
    this reason, unlike logging.FileHandler.

    Errors are routed through the standard logging.Handler.handleError()
    path (prints a traceback to stderr, never raises) so a disk problem
    here can never break the flow being logged -- the same reliability
    guarantee this module already had via a single FileHandler.
    """

    def emit(self, record):
        try:
            category = get_log_category()
            date_str = datetime.now().strftime("%Y-%m-%d")
            path = _LOG_DIR / f"{category}_{date_str}.log"
            message = self.format(record)
            with open(path, "a", encoding="utf-8") as f:
                f.write(message + "\n")
        except Exception:
            self.handleError(record)


if not _logger.handlers:

    _formatter = logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(_formatter)
    _logger.addHandler(_console_handler)

    _file_handler = _CategoryDatedFileHandler()
    _file_handler.setFormatter(_formatter)
    _logger.addHandler(_file_handler)


def _prefix(message):
    correlation_id = _correlation_id.get()
    if correlation_id is not None:
        return f"[{correlation_id}] {message}"
    return message


def log_phase(message):
    """
    A story beat -- describes what's happening in plain language.

    Example: log_phase("Patient search request received from ABDM")
    """
    _logger.info(_prefix(f"-> {message}"))


def log_api_call(description, url, response_code=None):
    """
    An outbound API call -- what we're doing, where, and (once known)
    what came back.

    Example: log_api_call("Reporting Patient Match to ABDM", "POST .../on-discover", 202)
    """
    if response_code is not None:
        _logger.info(_prefix(f"   [API] {description} -- {url} -> {response_code}"))
    else:
        _logger.info(_prefix(f"   [API] {description} -- {url}"))


def log_waiting(message):
    """
    What we're now waiting on the patient/app to do before anything
    else in this flow continues.

    Example: log_waiting("Waiting for the patient to choose to link these records in the PHR app")
    """
    _logger.info(_prefix(f"   [WAITING] {message}"))


def log_error(message):
    """A problem that stopped this flow from completing."""
    _logger.info(_prefix(f"   [ERROR] {message}"))
