from fastapi import APIRouter, Request

from server.callbacks.dispatcher import process_callback
from server.callbacks.utils.response import success

router = APIRouter()

@router.post("/callback")
async def callback(request: Request):

    body = await request.json()

    await process_callback(body, request)

    return success()