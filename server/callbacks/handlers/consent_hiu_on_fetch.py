from server.callbacks.services.consent_hiu_on_fetch_service import process_consent_hiu_on_fetch


async def handle_consent_hiu_on_fetch(callback_data):
    return await process_consent_hiu_on_fetch(callback_data)
