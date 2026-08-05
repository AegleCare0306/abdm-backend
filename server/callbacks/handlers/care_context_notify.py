from server.callbacks.services.care_context_notify_service import process_care_context_notify


async def handle_care_context_notify(callback_data):
    await process_care_context_notify(callback_data)
