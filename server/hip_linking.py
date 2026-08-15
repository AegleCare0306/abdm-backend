"""
HIP-Initiated Linking APIs (M2 doc §4.3.1-4.3.4).

Unlike UIL, this flow is initiated BY US (the HIP), not by ABDM. Both
outbound calls in this module are acknowledged with 202 Accepted and
have their real result delivered later via a separate callback --
structurally identical to how UIL's Discover/Link Init/Link Confirm
chain works (see server/linking.py, server/callbacks/services/).
"""

from collections import namedtuple

import requests

from server.config import HIECM_BASE_URL, X_CM_ID
from server.utils import generate_request_id, generate_timestamp, get_gateway_token, call_with_retry
from server.callbacks.repository.link_token_repository import save_pending_link_token
from server.callbacks.repository.patient_link_token_repository import get_patient_link_token
from server.callbacks.repository.care_context_link_repository import save_pending_care_context_link
from server.callbacks.repository.care_context_notify_repository import save_pending_care_context_notify
from server.callbacks.utils.flow_logger import log_phase, log_error
from server.callbacks.utils.api_capture import record_call

# Returned by generate_link_token() instead of a requests.Response when a
# saved link token already exists for this patient (see
# patient_link_token_repository.py) -- no outbound generate-token call is
# made in that case, so there's no Response object to return. Callers
# must check `isinstance(result, ReusedLinkToken)` before assuming
# `.status_code` exists. See generate_link_token()'s docstring for the
# full return contract.
ReusedLinkToken = namedtuple("ReusedLinkToken", ["link_token", "hip_id", "abha_address", "received_at"])


def _normalize_gender_for_abdm(gender):
    """
    ABDM's generate-token API expects a single-letter gender code -- the
    M2 doc's own request-body example shows `"gender": "M"`, not a full
    word. This codebase's patient data (server/data/master/patients.csv)
    stores full words ("Male"/"Female") for readability, so this
    normalizes at the boundary right before sending to ABDM, rather than
    assuming callers already pass the ABDM-expected shape.

    CONFIRMED REAL FAILURE (2026-08-04): sending "gender": "Male" (the
    raw CSV value, unnormalized) returned a real `400 Bad Request` from
    ABDM's sandbox -- generic (no ABDM-XXXX code in the body), but the
    only field differing from the doc's own worked example was this one.

    Args:
        gender (str): Raw gender value, e.g. "Male", "Female", "M", "F".
    Returns:
        str: A single-letter code ("M"/"F"/"O"). Falls back to the
            first letter of the input, uppercased, for any value not in
            the known mapping (e.g. an already-single-letter or
            unexpected value) -- passed through as best-effort rather
            than raising, since ABDM's actual accepted value set beyond
            M/F is not confirmed either.
    """
    if not gender:
        return gender
    mapping = {"male": "M", "female": "F", "other": "O", "m": "M", "f": "F", "o": "O"}
    normalized = mapping.get(gender.strip().lower())
    if normalized:
        return normalized
    return gender.strip()[:1].upper()


def _normalize_abha_number(abha_number, as_int=False):
    """
    ABDM expects abhaNumber as plain digits, no formatting dashes --
    confirmed via the real saved Postman collection ("Milestone 2 - New"):
    generate-token's request template sends it UNQUOTED (a raw JSON
    number, e.g. `91536782361862`), while link/carecontext's template
    sends the same digits as a QUOTED STRING (`"91536782361862"") --
    different shapes on each endpoint, but neither has dashes.

    This codebase's data (server/data/master/patients.csv) stores
    abha_number with display dashes ("91-6182-1610-5253") for
    readability -- this strips them right before sending, per endpoint,
    rather than assuming callers already pass ABDM's raw format.

    CONFIRMED REAL FAILURE (2026-08-04): generate-token returned a real
    `400 Bad Request` (generic body, no ABDM-XXXX code) while sending
    `"abhaNumber": "91-6182-1610-5253"` -- a quoted string with dashes,
    matching neither endpoint's actual expected shape.

    Args:
        abha_number (str): Raw value, e.g. "91-6182-1610-5253".
        as_int (bool): If True, returns an int (for generate-token's
            unquoted-number body field). If False (default), returns
            the digit-only string (for link/carecontext's quoted
            string body field).
    Returns:
        int | str | None: None if abha_number is falsy.
    """
    if not abha_number:
        return abha_number
    digits = "".join(ch for ch in abha_number if ch.isdigit())
    return int(digits) if as_int else digits


def generate_link_token(
    hip_id,
    abha_address,
    name,
    gender,
    year_of_birth,
    abha_number=None,
    selected_care_context_references=None,
):

    """
    Request a link token from ABDM for HIP-Initiated Linking (M2 doc
    §4.3.1) -- or reuse an already-saved one for this patient instead of
    calling ABDM again.

    REUSE BEHAVIOR: before making any outbound call, this checks
    patient_link_token_repository.get_patient_link_token(abha_address,
    hip_id) -- for this EXACT (patient, facility) pair, not the patient
    alone (fixed 2026-08-05; see that module's docstring for the real
    bug this replaced). If a token was already saved for this patient at
    this facility (persisted by generate_token_service.py.process_generate_token()
    once a prior on-generate-token callback confirmed one), the outbound
    generate-token call and the whole async callback wait are skipped
    entirely -- a ReusedLinkToken is returned instead of a
    requests.Response. This is deliberate, not just an optimization: the
    M2 doc documents `400 ABDM-1092 "Duplicate link token request"` as a
    real ABDM failure mode, confirming ABDM does not want repeated
    generate-token calls for a patient who already has a valid/pending
    token. A token saved for this patient at a DIFFERENT facility is
    never returned here and is treated exactly like no saved token at
    all -- this function falls through to the normal NEW-token path
    below for that facility.

    UNCONFIRMED (flagged, not guessed): there is no confirmed information
    anywhere -- doc or Postman collection -- about a link token's
    expiry/TTL, or how many times it can be reused before ABDM requires a
    new one. No expiry/TTL logic is implemented here as a result -- a
    saved token is reused indefinitely until ABDM's real behavior is
    confirmed otherwise. See patient_link_token_repository.py's module
    docstring and the Notion "Needs ABDM Spec Confirmation" tracker.

    Success on the NEW-token path (202 Accepted, no token in the body) is
    confirmed by both the official doc and a real captured Postman
    example -- the real `linkToken` is NOT returned here. It's delivered
    asynchronously via the on-generate-token callback (§4.3.2), handled
    by server/callbacks/services/generate_token_service.py.

    Failure scenarios ARE documented in the M2 doc for this endpoint
    (confirmed, not guessed):
        - Missing/invalid REQUEST-ID -> 403 ABDM-1030
        - Missing/invalid TIMESTAMP -> 400 ABDM-1016
        - Missing/invalid X-HIP-ID or X-CM-ID -> 403
        - Missing body -> 400 ABDM-1064
        - Duplicate link token request -> 400 ABDM-1092
        - Both abhaNumber and abhaAddress null -> 400 ABDM-1125
        - Malformed abhaNumber/abhaAddress/gender/yearOfBirth -> 400 ABDM-9999 variants
    None of these are special-cased below -- a non-202 response is just
    logged with its raw status/body and returned for the caller to
    inspect. None of this applies on the reuse path, since no request is
    made.

    Args:
        hip_id (str): Our HIP identifier for this facility. Required --
            there's no single "current HIP" constant in server/config.py.
            A saved token only reuses (the REUSE path below) if one
            exists for this EXACT hip_id -- a token saved for a
            different facility is never returned, and this falls
            through to the normal NEW-token path instead (fixed
            2026-08-05, see patient_link_token_repository.py).
        abha_address (str): Patient's ABHA address.
        name (str): Patient's name.
        gender (str): Patient's gender.
        year_of_birth (int): Patient's year of birth.
        abha_number (str, optional): Patient's ABHA number. Included in
            the request body only if provided. Unused on the reuse path.
        selected_care_context_references (list, optional): Care-context
            reference strings the caller has already chosen to link
            (added 2026-08-04, alongside select_care_contexts()'s
            multi_select mode) -- persisted into the pending session so
            generate_token_service.py's process_generate_token() can
            filter to just these records instead of linking everything
            search_patient() finds, once the on-generate-token callback
            arrives and auto-triggers link_care_context(). None (the
            default) means "link everything found," matching the prior
            behavior. Unused on the reuse path -- that path prompts for
            a selection directly at call time instead, since there's no
            callback wait involved.
    Returns:
        requests.Response: On the NEW-token path -- the raw generate-token
            call's response (202 expected). The real linkToken still
            arrives later via the on-generate-token callback, exactly as
            before this reuse logic was added.
        ReusedLinkToken: On the REUSE path -- no outbound call was made.
            Callers should proceed straight to link_care_context() using
            `.link_token` and `.hip_id` from this object; there is no
            callback to wait for in this case.
    Raises:
        requests.exceptions.RequestException: If the request fails
            (network error or non-2xx response). Never raised on the
            reuse path, since no request is made.
    """

    # CONFIRMED REAL BUG (2026-08-05), now fixed: this used to look up a
    # saved token by abha_address alone, and would silently reuse a
    # token issued for a DIFFERENT facility if one existed -- discarding
    # whatever facility/care-context selection the caller had just
    # made. get_patient_link_token() now requires an exact (abha_address,
    # hip_id) match, so a token saved for a different facility is
    # treated the same as no token existing at all, and this function
    # falls through to generating a brand-new one for the requested
    # hip_id below -- the standard behavior for any patient/facility
    # pair with nothing saved yet, not a special case. See
    # patient_link_token_repository.py's module docstring for the full
    # writeup.
    existing = get_patient_link_token(abha_address, hip_id)

    if existing is not None:
        log_phase(
            f"Reusing existing link token for {abha_address} "
            f"(received {existing['received_at']}) -- skipping generate-token call."
        )

        return ReusedLinkToken(
            link_token=existing["link_token"],
            hip_id=existing["hip_id"],
            abha_address=abha_address,
            received_at=existing["received_at"],
        )

    request_id = generate_request_id()

    # Stashed before the request is made, so the pending session exists
    # even if a slow/edge-case response still triggers a callback before
    # this function returns.
    save_pending_link_token(
        request_id,
        {
            "hip_id": hip_id,
            "abha_address": abha_address,
            "abha_number": abha_number,
            "selected_care_context_references": selected_care_context_references,
        },
    )

    url = f"{HIECM_BASE_URL}/v3/token/generate-token"

    payload = {
        "abhaAddress": abha_address,
        "name": name,
        "gender": _normalize_gender_for_abdm(gender),
        "yearOfBirth": year_of_birth,
    }

    if abha_number is not None:
        # as_int=True: this endpoint's Postman template sends abhaNumber
        # UNQUOTED (a raw JSON number) -- see _normalize_abha_number()'s
        # docstring.
        payload["abhaNumber"] = _normalize_abha_number(abha_number, as_int=True)

    headers = {
        "REQUEST-ID": request_id,
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-HIP-ID": hip_id,
        "X-CM-ID": X_CM_ID,
        "Content-Type": "application/json",
    }

    # RETRY: category 2 is a connection error/timeout or a 5xx/429/408
    # response -- see call_with_retry(). Not an ack to any inbound
    # callback -- this is the initiating call. IDEMPOTENCY (unconfirmed):
    # if a connection error/timeout happens after ABDM actually received
    # this request, a retry resends the same request_id (generated once,
    # above, before this block -- reused across every retry attempt of
    # THIS call, not re-minted per attempt). Whether ABDM treats a
    # same-REQUEST-ID resubmission as a safe no-op is not confirmed here
    # -- but this endpoint's own documented failure table (see this
    # function's docstring) already includes `400 ABDM-1092 "Duplicate
    # link token request"` as a real, handled outcome: if the first
    # attempt actually succeeded and the retry is genuinely redundant,
    # the worst case is this specific, already-anticipated 400 coming
    # back on the retry -- not an unhandled crash.
    try:
        response = call_with_retry(
            lambda: requests.post(
                url=url,
                json=payload,
                headers=headers,
                timeout=30,
            ),
            description="Link token generation",
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="generate-link-token",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"Link token generation failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    if response.status_code != 202:
        log_error(
            f"Link token generation returned unexpected status "
            f"{response.status_code}: {response_body}"
        )

    record_call(
        label="generate-link-token",
        direction="outgoing",
        method="POST",
        url=url,
        request_headers=headers,
        request_body=payload,
        response_status=response.status_code,
        response_headers=dict(response.headers),
        response_body=response_body,
    )

    return response

def is_duplicate_link_error(response_body):
    """
    True if response_body is ABDM's real, confirmed "this care context
    is already linked" response (2026-08-05) -- matched on the message
    text, not the error code, since the real observed code (ABDM-9999)
    doesn't match the doc's stated ABDM-1090 for this same message.
    Used to log this specific, expected case as informational rather
    than a genuine failure -- see link_care_context()'s use of this.
    """
    if not isinstance(response_body, dict):
        return False
    error = response_body.get("error")
    if not isinstance(error, dict):
        return False
    return (error.get("message") or "").strip() == "Duplicate HIP link request"


def _invert_for_notify(patient_records):
    """
    Inverts patient_records (build_patient_payload()'s output, grouped
    by hiType -- each group listing multiple careContexts) into the
    shape step 3 of the chain (notify_care_context_update()) needs: one
    entry per distinct care_context_reference, with every hiType that
    reference appeared under accumulated into a single list. A reference
    can legitimately appear in more than one hiType group (e.g. the same
    encounter having both an OPConsultation and a Prescription record) --
    both must end up together under that one reference, not as two
    separate entries.

    patient_reference is the same across every group for a given
    patient (record["referenceNumber"] in build_patient_payload()'s
    output) -- taken from whichever group is seen first.

    This is a small, separate transform consuming patient_records (the
    list link_care_context() already receives), not a second "patient
    payload builder" -- does not duplicate or replace
    build_patient_payload() in patient_transformer.py.

    Args:
        patient_records (list): Same shape link_care_context() already
            takes -- a list of {referenceNumber, display, careContexts,
            hiType, count} objects.
    Returns:
        tuple: (patient_reference (str | None), care_context_hi_types
            (dict of {care_context_reference: [hi_type, ...]})).
    """
    patient_reference = None
    care_context_hi_types = {}

    for group in patient_records:
        if patient_reference is None:
            patient_reference = group.get("referenceNumber")

        hi_type = group.get("hiType")

        for care_context in group.get("careContexts", []):
            reference = care_context.get("referenceNumber")
            hi_types = care_context_hi_types.setdefault(reference, [])
            if hi_type not in hi_types:
                hi_types.append(hi_type)

    return patient_reference, care_context_hi_types

def link_care_context(
    hip_id,
    abha_address,
    link_token,
    patient_records,
    abha_number=None,
):

    """
    Link care contexts to a patient's ABHA using a real link token
    obtained via the on-generate-token callback (M2 doc §4.3.3).

    Success (202 Accepted) is confirmed by both the official doc and a
    real Postman capture.

    Failure scenarios are documented in the doc similarly to
    generate_link_token() (ABDM-1062/1063/1038/1064/1090/1115/1031,
    9999 variants) -- not special-cased below; a non-202 response is
    just logged with its raw status/body and returned for the caller to
    inspect.

    CONFIRMED REAL FAILURE (2026-08-04): calling this without abha_number
    returned a real `400 ABDM-9999 "The Abha Number is mandatory"` --
    despite this function's own prior docstring (and the caller code, in
    both the reuse path and generate_token_service.py's auto-chained
    path) treating it as optional/omittable. It is NOT optional for this
    endpoint; both call sites were fixed the same day to always pass it.

    STEP 3 CHAINING (added 2026-08-04): before the outbound call, this
    inverts patient_records into the shape step 3 of the chain (Notify
    Care Context Update, §4.3.6) needs -- see _invert_for_notify() --
    and stashes it via save_pending_care_context_link(), keyed by this
    call's own REQUEST-ID. care_context_link_service.py's
    process_care_context_link() reads it back once the on_carecontext
    callback (§4.3.4) confirms success, and calls
    notify_care_context_update() once per distinct care context. This is
    a side effect of calling this function -- it does not change this
    function's own return value, arguments, or request/response
    behavior.

    Args:
        hip_id (str): Our HIP identifier for this facility.
        abha_address (str): Patient's ABHA address.
        link_token (str): The real link token delivered via the
            on-generate-token callback.
        patient_records (list): Patient/care-context payload, same
            shape UIL's Discover builds via build_patient_payload() --
            a list of {referenceNumber, display, careContexts, hiType,
            count} objects. Built by the caller, not by this function.
        abha_number (str): Patient's ABHA number. CONFIRMED REQUIRED by
            ABDM's real sandbox (see above) despite the `=None` default
            kept here for signature compatibility -- callers must
            supply a real value or expect a 400.
    Returns:
        requests.Response: Care context linking response.
    Raises:
        requests.exceptions.RequestException: If the request fails
            (network error or non-2xx response).
    """

    request_id = generate_request_id()

    # Stashed before the request is made, so the pending session exists
    # even if a slow/edge-case response still triggers a callback before
    # this function returns -- same reasoning as generate_link_token()'s
    # own pending-session save above. The on_carecontext callback body
    # doesn't echo back which care contexts were submitted, so this is
    # what care_context_link_service.py reads back to auto-trigger step
    # 3 (Notify Care Context Update) once the callback confirms success.
    patient_reference, care_context_hi_types = _invert_for_notify(patient_records)

    save_pending_care_context_link(
        request_id,
        {
            "hip_id": hip_id,
            "abha_address": abha_address,
            "link_token": link_token,
            "patient_reference": patient_reference,
            "care_context_hi_types": care_context_hi_types,
        },
    )

    url = f"{HIECM_BASE_URL}/hip/v3/link/carecontext"

    payload = {
        "abhaAddress": abha_address,
        "patient": patient_records,
    }

    if abha_number is not None:
        # as_int=False (default): this endpoint's Postman template sends
        # abhaNumber as a QUOTED STRING, unlike generate-token's unquoted
        # number -- see _normalize_abha_number()'s docstring.
        payload["abhaNumber"] = _normalize_abha_number(abha_number)

    headers = {
        "REQUEST-ID": request_id,
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-HIP-ID": hip_id,
        "X-CM-ID": X_CM_ID,
        "X-LINK-TOKEN": link_token,
        "Content-Type": "application/json",
    }

    # RETRY: category 2 is a connection error/timeout or a 5xx/429/408
    # response -- see call_with_retry(). Not an ack to any inbound
    # callback -- this is the initiating call, same request_id reused
    # across retry attempts. IDEMPOTENCY (unconfirmed, but low-risk in
    # practice): if a connection error/timeout retry resends a request
    # ABDM already processed, is_duplicate_link_error() immediately below
    # already treats ABDM's real, confirmed "Duplicate HIP link request"
    # response as an expected, non-error outcome (informational log, not
    # log_error) -- so a redundant retry lands on an already-handled
    # path, not a new failure mode.
    try:
        response = call_with_retry(
            lambda: requests.post(
                url=url,
                json=payload,
                headers=headers,
                timeout=30,
            ),
            description="Care context linking",
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="link-care-context",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"Care context linking failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    if response.status_code != 202:
        if is_duplicate_link_error(response_body):
            # CONFIRMED REAL RESPONSE (2026-08-05): re-submitting a care
            # context that's already linked returns a real 400 with
            # message "Duplicate HIP link request" -- the doc's own
            # §4.3.3 failure table calls this ABDM-1090, but the real
            # body observed tags it generically as ABDM-9999 instead
            # (worth noting -- the message text is the reliable
            # identifier here, not the code prefix). This isn't a
            # genuine failure the way the other 400s are -- it just
            # means nothing needs to change on ABDM's side, since the
            # link already exists. Logged as informational, not an
            # error, so it doesn't read as scary as an unexpected
            # failure -- the actual 400 response is still returned
            # unchanged below, so callers that need to know can still
            # tell.
            log_phase(
                f"Care context already linked (ABDM: \"Duplicate HIP link request\") -- "
                f"nothing to do, not treating this as a real failure."
            )
        else:
            log_error(
                f"Care context linking returned unexpected status "
                f"{response.status_code}: {response_body}"
            )

    record_call(
        label="link-care-context",
        direction="outgoing",
        method="POST",
        url=url,
        request_headers=headers,
        request_body=payload,
        response_status=response.status_code,
        response_headers=dict(response.headers),
        response_body=response_body,
    )

    return response

def notify_care_context_update(
    hip_id,
    abha_address,
    patient_reference,
    care_context_reference,
    hi_types,
    link_token,
    retry_count=0,
):

    """
    Notify ABDM that new care contexts are available for a patient
    already linked via HIP-Initiated Linking (M2 doc §4.3.6).

    DISCREPANCY: the doc's own §4.3.6 header table does NOT list
    X-LINK-TOKEN as a header for this endpoint, but the real captured
    Postman request (both its "Success" 202 and "Forbidden Error" 403
    examples) DOES send it -- included here as a required parameter,
    since real sandbox behavior overrides the doc's incomplete table.

    `link_token` must be a still-valid token for this patient (e.g.
    previously obtained via generate_link_token() -> the
    on-generate-token callback). This codebase does not currently
    persist link tokens for reuse -- link_care_context() deletes the
    pending session once used -- so supplying a valid token here is the
    caller's responsibility; no new persistence was added for this.

    Success (202 Accepted, empty body) confirmed by both the doc and a
    real captured Postman example.

    Failure scenarios documented in the doc (confirmed, not guessed):
        - Missing/invalid REQUEST-ID -> 403/400 ABDM-1030
        - Missing/invalid TIMESTAMP -> 403/400 ABDM-1016
        - Missing/invalid X-CM-ID -> 403
        - Missing/invalid X-HIP-ID -> 403
        - Unknown X-HIP-ID -> 400 ABDM-1035
    None of these are special-cased below -- a non-202 response is just
    logged with its raw status/body and returned for the caller to
    inspect.

    Args:
        hip_id (str): Our HIP identifier for this facility.
        abha_address (str): Patient's ABHA address.
        patient_reference (str): Patient reference within our system.
        care_context_reference (str): Care context reference being
            notified.
        hi_types (list): HI types for this care context.
        link_token (str): A still-valid link token for this patient.
        retry_count (int): 0 for a normal call. Set to 1 by
            care_context_notify_service.py's process_care_context_notify()
            when retrying after a real, confirmed ABDM-1006 "No links
            found for the patient in the given HIP" timing race
            (2026-08-04) -- capped at one retry so a persistently
            failing call doesn't loop forever. Stored in the saved
            pending session, not sent to ABDM.
    Returns:
        requests.Response: Notify response.
    Raises:
        requests.exceptions.RequestException: If the request fails
            (network error or non-2xx response).
    """

    request_id = generate_request_id()

    # Stashed before the request is made -- same reasoning as
    # link_care_context()'s own pending session: the on-notify callback
    # body doesn't echo back what was notified, so this is what
    # care_context_notify_service.py reads back if a retry is needed.
    save_pending_care_context_notify(
        request_id,
        {
            "hip_id": hip_id,
            "abha_address": abha_address,
            "patient_reference": patient_reference,
            "care_context_reference": care_context_reference,
            "hi_types": hi_types,
            "link_token": link_token,
            "retry_count": retry_count,
        },
    )

    url = f"{HIECM_BASE_URL}/hip/v3/link/context/notify"

    payload = {
        "notification": {
            "patient": {
                "id": abha_address,
            },
            "careContext": {
                "patientReference": patient_reference,
                "careContextReference": care_context_reference,
            },
            "hiTypes": hi_types,
            "date": generate_timestamp(),
            "hip": {
                "id": hip_id,
            },
        }
    }

    headers = {
        "REQUEST-ID": request_id,
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-HIP-ID": hip_id,
        "X-CM-ID": X_CM_ID,
        "X-LINK-TOKEN": link_token,
        "Content-Type": "application/json",
    }

    # RETRY: category 2 is a connection error/timeout or a 5xx/429/408
    # response -- see call_with_retry(). Not an ack to any inbound
    # callback. IDEMPOTENCY (unconfirmed): this is a "new care context
    # available" notification, not a state-setting call -- ABDM's real
    # behavior for a duplicate notify of the same care context is not
    # confirmed in this codebase's docs, flagged here rather than
    # assumed. Distinct from retry_count (this function's own param,
    # used by care_context_notify_service.py for the separate,
    # already-existing ABDM-1006 timing-race retry) -- that's a
    # different retry mechanism at a different layer and is untouched by
    # this wrapper, which only covers this one HTTP attempt.
    try:
        response = call_with_retry(
            lambda: requests.post(
                url=url,
                json=payload,
                headers=headers,
                timeout=30,
            ),
            description="Care context update notify",
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="notify-care-context-update",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"Care context update notify failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    if response.status_code != 202:
        log_error(
            f"Care context update notify returned unexpected status "
            f"{response.status_code}: {response_body}"
        )

    record_call(
        label="notify-care-context-update",
        direction="outgoing",
        method="POST",
        url=url,
        request_headers=headers,
        request_body=payload,
        response_status=response.status_code,
        response_headers=dict(response.headers),
        response_body=response_body,
    )

    return response

def send_sms_notification(hip_id, hip_name, phone_no):

    """
    Ask ABDM to send an SMS notification to a patient's phone about
    pending care-context links (M2 doc §4.3.8).

    RETRY: category 2 is a connection error/timeout or a 5xx/429/408
    response -- see call_with_retry(). Confirmed by Aayush (2026-08-14):
    same uniform policy as every other outbound call in this module,
    despite this endpoint asking ABDM to trigger a real SMS send to a
    patient's phone -- a deliberate choice to keep the retry policy
    simple and consistent rather than carve out SMS-specific behavior
    before real sandbox testing shows whether that's actually needed.
    IDEMPOTENCY (unconfirmed, still worth knowing): a same-payload retry
    after an ambiguous timeout could, in principle, result in a patient
    receiving a duplicate SMS if ABDM had actually accepted the first
    attempt -- unlike link_care_context()'s is_duplicate_link_error(),
    there's no known "already handled gracefully" response shape for
    this endpoint to fall back on. Revisit this decision if real sandbox
    testing ever shows duplicate SMS deliveries.

    No X-HIP-ID header is sent on this endpoint -- confirmed absent
    from both the doc's header table and the real Postman capture; the
    HIP id/name are carried in the body instead. Authorization IS
    required per the doc's header table (Bearer gateway token) -- it
    was mistakenly omitted from this file's first draft and has been
    corrected.

    Two distinct REQUEST-ID-shaped values are generated here: the
    header REQUEST-ID tracks the transaction (matching convention
    everywhere else in this codebase), while the body-level `requestId`
    "uniquely identifies each notification request" per the doc and is
    what the callback's resp.requestId correlates back to -- these must
    NOT be the same value.

    Success (202 Accepted) is confirmed by the doc's text. The real
    Postman capture doesn't have a saved status code for this one, but
    its response body is literally a note confirming the async pattern:
    "This response is expected on webhook url
    .../api/v3/patients/sms/on-notify".

    Failure scenarios documented in the doc:
        - Missing/invalid REQUEST-ID or TIMESTAMP -> 403/400
        - Missing/invalid X-CM-ID -> 403
        - Unknown HIP id -> 400 ABDM-1035
    None of these are special-cased below -- a non-202 response is just
    logged with its raw status/body and returned for the caller to
    inspect.

    Args:
        hip_id (str): Our HIP identifier, sent in the body.
        hip_name (str): Our HIP name, sent in the body.
        phone_no (str): Patient's phone number to notify.
    Returns:
        requests.Response: SMS notification response.
    Raises:
        requests.exceptions.RequestException: If the request fails
            (network error or non-2xx response).
    """

    url = f"{HIECM_BASE_URL}/hip/v3/link/patient/links/sms/notify2"

    payload = {
        "requestId": generate_request_id(),
        "timestamp": generate_timestamp(),
        "notification": {
            "phoneNo": phone_no,
            "hip": {
                "id": hip_id,
                "name": hip_name,
            },
        },
    }

    headers = {
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-CM-ID": X_CM_ID,
        "Content-Type": "application/json",
    }

    try:
        response = call_with_retry(
            lambda: requests.post(
                url=url,
                json=payload,
                headers=headers,
                timeout=30,
            ),
            description="SMS notification send",
        )
    except requests.exceptions.RequestException as exc:
        record_call(
            label="send-sms-notification",
            direction="outgoing",
            method="POST",
            url=url,
            request_headers=headers,
            request_body=payload,
            response_status=None,
            response_body=f"RequestException: {exc}",
        )
        log_error(f"SMS notification send failed: {exc}")
        raise

    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    if response.status_code != 202:
        log_error(
            f"SMS notification send returned unexpected status "
            f"{response.status_code}: {response_body}"
        )

    record_call(
        label="send-sms-notification",
        direction="outgoing",
        method="POST",
        url=url,
        request_headers=headers,
        request_body=payload,
        response_status=response.status_code,
        response_headers=dict(response.headers),
        response_body=response_body,
    )

    return response
