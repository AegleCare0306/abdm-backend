import uuid

from fastapi import Request

from server.callbacks.utils.storage import save_callback
from server.callbacks.utils.api_capture import record_call
from server.callbacks.handlers.discover import handle_discover
from server.callbacks.handlers.link_init import handle_link_init
from server.callbacks.handlers.link_confirm import handle_link_confirm
from server.callbacks.handlers.consent_notify import handle_consent_notify
from server.callbacks.handlers.health_information_request import handle_health_information_request
from server.callbacks.handlers.generate_token import handle_generate_token
from server.callbacks.handlers.care_context_link import handle_care_context_link
from server.callbacks.handlers.care_context_notify import handle_care_context_notify
from server.callbacks.handlers.sms_notify import handle_sms_notify
from server.callbacks.utils.flow_logger import log_error, set_correlation_id


async def dispatch_callback(
    callback_type: str,
    request: Request,
):
    """
    Every route in router.py calls this, then unconditionally returns
    success() to ABDM regardless of what happens here -- so this function
    must never raise. Anything unexpected (a malformed request, a disk
    write failure archiving the callback, an unregistered callback type)
    is caught and logged rather than propagating up as an unhandled 500,
    since ABDM's gateway should always get its acknowledgement even if
    something on our side went wrong processing the callback internally.
    """

    try:
        correlation_id = str(uuid.uuid4())[:8]
        set_correlation_id(correlation_id)

        headers = dict(request.headers)

        try:
            body = await request.json()
        except Exception:
            body = {}

        callback_data = {
            "headers": headers,
            "body": body,
        }

        # Full raw callback payload is archived to storage/callbacks/*.json by
        # save_callback() -- nothing printed to console here, since each
        # service below tells its own story as it processes the callback.
        save_callback(callback_data, correlation_id=correlation_id)

        record_call(
            label=callback_type,
            direction="incoming",
            method="POST",
            url=str(request.url.path),
            request_headers=headers,
            request_body=body,
            response_status=200,
            response_headers=None,
            response_body={"status": "OK"},
        )

        handlers = {
            "discover": handle_discover,
            "care_context_init": handle_link_init,
            "care_context_confirm": handle_link_confirm,
            "consent_notify": handle_consent_notify,
            "health_information_request": handle_health_information_request,
            "generate_token": handle_generate_token,
            "care_context_link": handle_care_context_link,
            "care_context_notify": handle_care_context_notify,
            "sms_notify": handle_sms_notify,
        }

        handler = handlers.get(callback_type)

        if handler:
            await handler(callback_data)
        else:
            log_error(f"No handler registered for callback type '{callback_type}'")

    except Exception as exc:
        log_error(f"Dispatching '{callback_type}' callback failed unexpectedly: {exc}")
