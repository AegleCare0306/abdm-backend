from server.callbacks.services.consent_init_on_init_service import process_consent_hiu_on_init


async def handle_consent_hiu_on_init(callback_data):
    return await process_consent_hiu_on_init(callback_data)
