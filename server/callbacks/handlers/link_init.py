from server.callbacks.services.link_init_service import process_link_init


async def handle_link_init(callback_data):
    await process_link_init(callback_data)