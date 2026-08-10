from server.callbacks.services.consent_hiu_notify_service import process_consent_hiu_notify


async def handle_consent_hiu_notify(callback_data):
    return await process_consent_hiu_notify(callback_data)
