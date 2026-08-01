import json
from pathlib import Path
from datetime import datetime


CALLBACK_FOLDER = Path("storage/callbacks")

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