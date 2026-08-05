from server.callbacks.utils.flow_logger import log_phase, log_error


async def process_sms_notify(callback_data):

    try:
        log_phase("ABDM acknowledged the SMS notification (POST /api/v3/patients/sms/on-notify)")

        body = callback_data["body"]

        resp_request_id = body.get("resp", {}).get("requestId")
        status = body.get("status")
        error = body.get("error")

        if error:
            log_error(f"SMS notification failed for requestId {resp_request_id}: {error}")
        else:
            log_phase(f"SMS notification acknowledged for requestId {resp_request_id}: {status}")

    except Exception as exc:
        log_error(f"SMS Notify callback processing failed unexpectedly: {exc}")
        return
