"""
Flow Logger.

Replaces scattered print() statements across the M2 callback services with
a consistent, narrative logging style -- each call describes what's
actually happening in plain language, not just a technical function name.

Writes to both the console (for live viewing while testing) and a
persistent log file (logs/flow.log, already covered by .gitignore's
*.log pattern) so nothing is lost between server restarts.
"""

import contextvars
import logging
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_logger = logging.getLogger("abdm_flow")
_logger.setLevel(logging.INFO)

if not _logger.handlers:

    _formatter = logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(_formatter)
    _logger.addHandler(_console_handler)

    _file_handler = logging.FileHandler(_LOG_DIR / "flow.log", encoding="utf-8")
    _file_handler.setFormatter(_formatter)
    _logger.addHandler(_file_handler)


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
