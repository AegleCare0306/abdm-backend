from server.callbacks.services.link_confirm_service import process_link_confirm


async def handle_link_confirm(callback_data):
    return await process_link_confirm(callback_data)