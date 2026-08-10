"""
Shared file-attachment helpers for the DocumentReference/Binary/Media
resource builders.
"""

import base64
from pathlib import Path

# server/fhir_builders/attachment_utils.py -> parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

CONTENT_TYPE_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def content_type_for_path(file_path):
    """
    ".pdf" -> "application/pdf", ".jpg"/".jpeg" -> "image/jpeg". Falls back
    to "application/octet-stream" for anything else rather than raising --
    an unrecognized extension shouldn't crash bundle assembly.
    """
    ext = Path(file_path).suffix.lower()
    return CONTENT_TYPE_BY_EXTENSION.get(ext, "application/octet-stream")


def read_attachment(file_path):
    """
    Reads a file (path relative to the repo root, matching how
    documents.csv's file_path column is stored) and returns
    (content_type, base64_data, size_bytes).
    """

    absolute_path = _REPO_ROOT / file_path
    raw_bytes = absolute_path.read_bytes()

    return (
        content_type_for_path(file_path),
        base64.b64encode(raw_bytes).decode(),
        len(raw_bytes),
    )
