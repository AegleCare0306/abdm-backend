import json
from pathlib import Path
from datetime import datetime


# ANCHOR FIX (tracker case M2-34/M3-7): was a bare relative path
# (`Path("storage/callbacks")`), resolved against the process's current
# working directory at IMPORT time -- launching the server from any
# directory other than the repo root silently created/read a SECOND,
# disconnected `storage/callbacks/` tree there instead of the real one,
# splitting captured-callback data across two locations depending on
# launch directory. Anchored to this file's own location instead, same
# convention already used by json_file_store.py's `_STORAGE_ROOT` and
# flow_logger.py's `_LOG_DIR`, so it no longer depends on cwd.
# server/callbacks/utils/storage.py -> parents[3] is the repo root,
# same depth convention as json_file_store.py's own comment.
CALLBACK_FOLDER = Path(__file__).resolve().parents[3] / "storage" / "callbacks"

CALLBACK_FOLDER.mkdir(parents=True, exist_ok=True)


def save_callback(body: dict, correlation_id: str = None):

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    if correlation_id:
        filename = f"{timestamp}_{correlation_id}.json"
    else:
        filename = f"{timestamp}.json"

    filepath = CALLBACK_FOLDER / filename

    body_to_save = {**body, "_correlation_id": correlation_id} if correlation_id else body

    with open(filepath, "w", encoding="utf-8") as f:

        json.dump(body_to_save, f, indent=4)