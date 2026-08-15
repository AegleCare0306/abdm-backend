from server.callbacks.repository.pending_health_information_request_repository import (
    get_pending_health_information_request,
    get_request_id_for_transaction_id,
    link_transaction_id,
)
from server.callbacks.utils.flow_logger import log_phase, log_waiting, log_error


async def process_health_information_hiu_on_request(callback_data):
    """
    Processes the Health Information Request on-request ack callback (M3
    Block 2, step 2).

    CONFIRMED PATH: the URL this handler is wired to
    (/api/v3/hiu/health-information/on-request, see
    server/callbacks/router.py) is stated explicitly in the M3 spec doc
    (M3_Dcoument_16_02_2026_2319bac7bf.docx, section 5.3.2 "Data flow --
    call back to HIU"), which also includes a real captured webhook.site
    example of an actual ABDM call hitting this exact path. Originally
    built as a guess (following M3 Block 1's own /api/v3/hiu/<resource>/
    on-<verb> convention) before this doc section was found and
    cross-checked.

    Confirmed inbound body shape (matches both the Postman collection's
    "Note: Expected response on call back" annotation on the Health
    Information Request example, and the spec doc's own body-parameter
    table + captured example, verbatim):
        {"hiRequest": {"transactionId": "...", "sessionStatus": "REQUESTED"},
         "response": {"requestId": "..."}}

    Just correlates response.requestId back to the pending session saved
    by initiate_health_information_request() (server/hiu_health_information.py)
    and records the real transactionId against it, so the later data push
    (which arrives keyed by transactionId, not our REQUEST-ID) can find
    its way back to this session. No outbound call is made here and no
    further chaining happens -- this just waits for the HIP to push
    encrypted records directly to our dataPushUrl.
    """
    try:
        log_phase("Data request acknowledged by ABDM (POST /api/v3/hiu/health-information/on-request)")

        body = callback_data["body"]
        request_id = (body.get("response") or {}).get("requestId")

        if not request_id:
            log_error("on-request callback missing response.requestId -- cannot correlate to a pending health information request.")
            return

        pending = get_pending_health_information_request(request_id)

        if pending is None:
            log_error(f"No pending health information request found for requestId {request_id}.")
            return

        hi_request = body.get("hiRequest") or {}
        transaction_id = hi_request.get("transactionId")
        session_status = hi_request.get("sessionStatus")

        if not transaction_id:
            log_error(f"on-request callback missing hiRequest.transactionId for requestId {request_id}.")
            return

        # TRANSACTION-ID COLLISION CHECK (edge-case-review pass, tracker
        # case M3-2): see get_request_id_for_transaction_id()'s own
        # docstring for the full reasoning -- refuse to relink a
        # transactionId that's already linked to a DIFFERENT pending
        # requestId's session, rather than silently overwriting the
        # index and crossing two overlapping requests' encryption keys.
        # Same requestId claiming the same transactionId again (a benign
        # retry of this exact callback) is allowed through unchanged.
        existing_request_id = get_request_id_for_transaction_id(transaction_id)
        if existing_request_id is not None and existing_request_id != request_id:
            log_error(
                f"transactionId {transaction_id} is already linked to a different pending "
                f"requestId ({existing_request_id!r}) -- refusing to relink it to requestId "
                f"{request_id!r}. Ignoring this on-request callback as a probable "
                f"cross-request mixup/replay rather than crossing two sessions' encryption keys."
            )
            return

        link_transaction_id(request_id, transaction_id)

        log_phase(f"transactionId {transaction_id} recorded for requestId {request_id} (sessionStatus={session_status})")
        log_waiting("Waiting for the HIP to push encrypted records directly to our dataPushUrl")

    except Exception as exc:
        log_error(f"Health Information on-request callback processing failed unexpectedly: {exc}")
        return
