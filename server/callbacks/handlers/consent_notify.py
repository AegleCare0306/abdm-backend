from server.callbacks.services.consent_notify_service import process_consent_notify


async def handle_consent_notify(callback_data):
    return await process_consent_notify(callback_data)