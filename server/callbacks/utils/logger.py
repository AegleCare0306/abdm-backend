import json
from datetime import datetime


def log_callback(body: dict):

    print("\n" + "=" * 80)

    print(f"Time : {datetime.now()}")

    print(json.dumps(body, indent=4))

    print("=" * 80)