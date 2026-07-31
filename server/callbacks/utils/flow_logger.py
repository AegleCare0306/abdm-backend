"""
Flow Logger.

Replaces scattered print() statements across the M2 callback services with
a consistent, narrative logging style -- each call describes what's
actually happening in plain language, not just a technical function name.

Writes to both the console (for live viewing while testing) and a
persistent log file (logs/flow.log, already covered by .gitignore's
*.log pattern) so nothing is lost between server restarts.
"""

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


def log_phase(message):
    """
    A story beat -- describes what's happening in plain language.

    Example: log_phase("Patient search request received from ABDM")
    """
    _logger.info(f"-> {message}")


def log_api_call(description, url, response_code=None):
    """
    An outbound API call -- what we're doing, where, and (once known)
    what came back.

    Example: log_api_call("Reporting Patient Match to ABDM", "POST .../on-discover", 202)
    """
    if response_code is not None:
        _logger.info(f"   [API] {description} -- {url} -> {response_code}")
    else:
        _logger.info(f"   [API] {description} -- {url}")


def log_waiting(message):
    """
    What we're now waiting on the patient/app to do before anything
    else in this flow continues.

    Example: log_waiting("Waiting for the patient to choose to link these records in the PHR app")
    """
    _logger.info(f"   [WAITING] {message}")


def log_error(message):
    """A problem that stopped this flow from completing."""
    _logger.info(f"   [ERROR] {message}")
