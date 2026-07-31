# NOTE (2026-07-31): disabled during M2 documentation review. This was an
# early, plain print()-based callback logger -- superseded by
# server/callbacks/utils/flow_logger.py, which every M2 service now imports
# from (log_phase / log_api_call / log_waiting / log_error) and which also
# writes to logs/flow.log, not just the console. Confirmed via repo-wide
# search that log_callback() is not imported/called anywhere. Commented out
# rather than deleted so the history of what it replaced stays visible.
#
# import json
# from datetime import datetime
#
#
# def log_callback(body: dict):
#
#     print("\n" + "=" * 80)
#
#     print(f"Time : {datetime.now()}")
#
#     print(json.dumps(body, indent=4))
#
#     print("=" * 80)