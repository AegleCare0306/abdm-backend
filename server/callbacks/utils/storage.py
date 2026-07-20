import json
from pathlib import Path
from datetime import datetime


CALLBACK_FOLDER = Path("storage/callbacks")

CALLBACK_FOLDER.mkdir(parents=True, exist_ok=True)


def save_callback(body: dict):

    filename = datetime.now().strftime("%Y%m%d_%H%M%S_%f.json")

    filepath = CALLBACK_FOLDER / filename

    with open(filepath, "w", encoding="utf-8") as f:

        json.dump(body, f, indent=4)