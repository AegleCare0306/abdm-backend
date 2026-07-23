from fastapi import APIRouter, Request

from server.callbacks.dispatcher import dispatch_callback
from server.callbacks.utils.response import success

router = APIRouter()


@router.post("/api/v3/hip/token/on-generate-token")
async def on_generate_token(request: Request):

    await dispatch_callback(
        callback_type="generate_token",
        request=request,
    )

    return success()


@router.post("/api/v3/link/on_carecontext")
async def on_carecontext(request: Request):

    await dispatch_callback(
        callback_type="care_context_link",
        request=request,
    )

    return success()


@router.post("/api/v3/consent/request/hip/notify")
async def consent_request_notify(request: Request):

    await dispatch_callback(
        callback_type="consent_notify",
        request=request,
    )

    return success()


@router.post("/api/v3/hip/patient/care-context/discover")
async def discover_care_context(request: Request):

    await dispatch_callback(
        callback_type="discover",
        request=request,
    )

    return success()

@router.post("/api/v3/hip/link/care-context/init")
async def care_context_init(request: Request):

    await dispatch_callback(
        callback_type="care_context_init",
        request=request,
    )

    return success()