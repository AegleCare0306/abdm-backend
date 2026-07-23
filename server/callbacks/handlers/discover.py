from server.callbacks.services.discover_service import process_discover


async def handle_discover(callback_data):

    await process_discover(callback_data)