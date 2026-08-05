from server.callbacks.services.sms_notify_service import process_sms_notify


async def handle_sms_notify(callback_data):
    await process_sms_notify(callback_data)
