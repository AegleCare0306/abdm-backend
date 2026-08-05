from server.callbacks.services.care_context_link_service import process_care_context_link


async def handle_care_context_link(callback_data):
    await process_care_context_link(callback_data)
