from fastapi import APIRouter, Depends, Request

from server.callbacks.dispatcher import dispatch_callback
from server.callbacks.utils.response import success
from server.callbacks.utils.jwt_auth import verify_abdm_callback

router = APIRouter()

# Applied to every route below via dependencies=[Depends(verify_abdm_callback)]
# rather than copy-pasted per handler -- see
# server/callbacks/utils/jwt_auth.py's own module docstring for what this
# actually verifies (signature against ABDM's live JWKS, iss, exp, and a
# sanity check on aud/azp) and why. Runs before the route body (and
# therefore before dispatch_callback()), so an unverified request never
# reaches application logic and gets a real 401.
_AUTH = [Depends(verify_abdm_callback)]


@router.post("/api/v3/hip/token/on-generate-token", dependencies=_AUTH)
async def on_generate_token(request: Request):

    await dispatch_callback(
        callback_type="generate_token",
        request=request,
    )

    return success()


@router.post("/api/v3/link/on_carecontext", dependencies=_AUTH)
async def on_carecontext(request: Request):

    await dispatch_callback(
        callback_type="care_context_link",
        request=request,
    )

    return success()


@router.post("/api/v3/consent/request/hip/notify", dependencies=_AUTH)
async def consent_request_notify(request: Request):

    await dispatch_callback(
        callback_type="consent_notify",
        request=request,
    )

    return success()


@router.post("/api/v3/hip/patient/care-context/discover", dependencies=_AUTH)
async def discover_care_context(request: Request):

    await dispatch_callback(
        callback_type="discover",
        request=request,
    )

    return success()

@router.post("/api/v3/hip/link/care-context/init", dependencies=_AUTH)
async def care_context_init(request: Request):

    await dispatch_callback(
        callback_type="care_context_init",
        request=request,
    )

    return success()

@router.post("/api/v3/hip/link/care-context/confirm", dependencies=_AUTH)
async def care_context_confirm(request: Request):

    await dispatch_callback(
        callback_type="care_context_confirm",
        request=request,
    )

    return success()

@router.post("/api/v3/hip/health-information/request", dependencies=_AUTH)
async def health_information_request(
    request: Request,
):

    await dispatch_callback(
        callback_type="health_information_request",
        request=request,
    )

    return success()

@router.post("/api/v3/links/context/on-notify", dependencies=_AUTH)
async def links_context_on_notify(request: Request):

    await dispatch_callback(
        callback_type="care_context_notify",
        request=request,
    )

    return success()

@router.post("/api/v3/patients/sms/on-notify", dependencies=_AUTH)
async def patients_sms_on_notify(request: Request):

    await dispatch_callback(
        callback_type="sms_notify",
        request=request,
    )

    return success()

@router.post("/api/v3/hiu/consent/request/on-init", dependencies=_AUTH)
async def hiu_consent_request_on_init(request: Request):

    await dispatch_callback(
        callback_type="consent_hiu_on_init",
        request=request,
    )

    return success()

@router.post("/api/v3/hiu/consent/request/notify", dependencies=_AUTH)
async def hiu_consent_request_notify(request: Request):

    await dispatch_callback(
        callback_type="consent_hiu_notify",
        request=request,
    )

    return success()

@router.post("/api/v3/hiu/consent/on-fetch", dependencies=_AUTH)
async def hiu_consent_on_fetch(request: Request):

    await dispatch_callback(
        callback_type="consent_hiu_on_fetch",
        request=request,
    )

    return success()

@router.post("/api/v3/hiu/health-information/on-request", dependencies=_AUTH)
async def hiu_health_information_on_request(request: Request):
    # CONFIRMED: this exact URL is stated explicitly in the M3 spec doc
    # (M3_Dcoument_16_02_2026_2319bac7bf.docx, section 5.3.2 "Data flow --
    # call back to HIU": "URL: {callback_url}/api/v3/hiu/health-information/
    # on-request"), and that section includes a real captured webhook.site
    # example showing an actual ABDM call hitting this exact path with the
    # body shape already implemented below. Originally built as a guess
    # (following the /api/v3/hiu/<resource>/on-<verb> convention used by
    # M3 Block 1's 3 callbacks) before this doc section was found and
    # cross-checked -- confirmed correct, not just a lucky guess.
    await dispatch_callback(
        callback_type="health_information_hiu_on_request",
        request=request,
    )

    return success()

@router.post("/api/v3/hiu/health-information/push", dependencies=_AUTH)
async def hiu_health_information_push(request: Request):
    # Our own choice of path -- we supply it ourselves as dataPushUrl in
    # initiate_health_information_request() (server/hiu_health_information.py),
    # so this one is confirmed-by-construction, not a guess.
    await dispatch_callback(
        callback_type="health_information_hiu_push",
        request=request,
    )

    return success()

