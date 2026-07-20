from server.callbacks.utils.logger import log_callback
from server.callbacks.utils.storage import save_callback


async def process_callback(body: dict):

    log_callback(body)

    save_callback(body)

    print("Callback processing completed.")