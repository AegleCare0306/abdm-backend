from server.callbacks.services.generate_token_service import process_generate_token


async def handle_generate_token(callback_data):
    await process_generate_token(callback_data)
