from fastapi import Request

from server.callbacks.utils.logger import log_callback
from server.callbacks.utils.storage import save_callback

from server.callbacks.handlers.discover import handle_discover
from server.callbacks.handlers.link_init import handle_link_init
from server.callbacks.handlers.link_confirm import handle_link_confirm


async def dispatch_callback(
    callback_type: str,
    request: Request,
):

    headers = dict(request.headers)

    try:
        body = await request.json()
    except Exception:
        body = {}

    callback_data = {
        "headers": headers,
        "body": body,
    }

    log_callback(callback_data)
    save_callback(callback_data)

    handlers = {
        "discover": handle_discover,
        "care_context_init": handle_link_init,
        "care_context_confirm": handle_link_confirm,
    }

    handler = handlers.get(callback_type)

    if handler:
        await handler(callback_data)
    else:
        print(f"No handler registered for '{callback_type}'")

    print(f"{callback_type} callback processed.")