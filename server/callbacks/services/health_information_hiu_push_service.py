"""
Processes the HIP's direct data push to our own dataPushUrl (M3 Block 2,
step 3 -- NOT delivered through the ABDM gateway, unlike every other
callback in this codebase). Mirror image of M2's own
health_information_request_service.py._push_and_notify(): that function
is the SENDER side (HIP encrypts and pushes); this module is the
RECEIVER side (HIU receives and decrypts).
"""

import asyncio
import hashlib
import json

from server.fidelius_crypto import decrypt_health_data, from_x509_public_key
from server.healthinformation import send_health_information_notify
from server.utils import print_api_response, generate_timestamp, generate_safe_past_timestamp
from server.callbacks.repository.pending_health_information_request_repository import (
    get_pending_health_information_request_by_transaction_id,
)
from server.callbacks.repository.hiu_health_information_repository import (
    save_hiu_health_information,
    get_hiu_health_information,
)
from server.callbacks.repository.hiu_consent_repository import get_hiu_consent
from server.callbacks.utils.flow_logger import log_phase, log_api_call, log_waiting, log_error


def _compute_checksum(encrypted_content):
    """
    MD5 hex digest of the encrypted content. Duplicated (not imported)
    from server/callbacks/services/health_information_request_service.py's
    identically-named, identically-implemented private helper -- same
    algorithm, confirmed the same way (see that module's own docstring on
    this function: confirmed via an independent source documenting real
    ABDM HIP integrations, not guessed). Kept as a local copy rather than
    a cross-module import of a leading-underscore "private" helper, which
    would also drag in that entire M2 module's heavy transitive
    dependency chain (fhir_builders, tools.dummy_emr, etc.) just for one
    MD5 one-liner.
    """
    return hashlib.md5(encrypted_content.encode("utf-8")).hexdigest()


def _decrypt_entries(entries, authorized_care_context_refs, consent_id, hip_public_key_raw, our_key_material, hip_key_material):
    """
    Checksum-verifies, consent-scope-checks, and decrypts every entry in
    one push. Plain synchronous function -- see this module's own
    process_health_information_hiu_push() for why it's called via
    asyncio.to_thread() rather than inline (tracker case M2-5: this does
    real CPU-bound decryption work, which was previously running directly
    inside the async handler and blocking the whole event loop for its
    duration).

    Returns:
        dict: {care_context_reference: {"hi_status", "description",
            "bundle", "received_at"}} for every entry processed.
    """
    care_contexts = {}

    for entry in entries:
        care_context_reference = entry.get("careContextReference")
        content = entry.get("content")
        claimed_checksum = entry.get("checksum")

        if not content or not care_context_reference:
            log_error(f"Skipping malformed entry (missing content/careContextReference): {entry}")
            continue

        if care_context_reference not in authorized_care_context_refs:
            log_error(
                f"Rejecting care context {care_context_reference} -- not covered by consent "
                f"{consent_id!r}'s own granted careContexts. Refusing to decrypt/store it."
            )
            care_contexts[care_context_reference] = {
                "hi_status": "ERRORED",
                "description": "Care context not covered by the granted consent",
                "bundle": None,
                "received_at": generate_timestamp(),
            }
            continue

        actual_checksum = _compute_checksum(content)

        if actual_checksum != claimed_checksum:
            log_error(f"Checksum mismatch for care context {care_context_reference} -- expected {claimed_checksum}, computed {actual_checksum}.")
            care_contexts[care_context_reference] = {
                "hi_status": "ERRORED",
                "description": "Checksum mismatch",
                "bundle": None,
                "received_at": generate_timestamp(),
            }
            continue

        if hip_public_key_raw is None:
            care_contexts[care_context_reference] = {
                "hi_status": "ERRORED",
                "description": "Could not decode HIP's public key",
                "bundle": None,
                "received_at": generate_timestamp(),
            }
            continue

        try:
            # We (the HIU) are the receiving/decrypting side here --
            # ECDH's shared secret is symmetric (our_priv * their_pub
            # == their_priv * our_pub, and the nonce XOR combining
            # the salt/IV is commutative too), so
            # decrypt_health_data()'s HIP-flavored "sender"/
            # "requester" param names just need our own key material
            # consistently on one side and the HIP's on the other --
            # which literal param each goes under doesn't change the
            # math. Same role-swap tools/verify_fidelius.py's own
            # round-trip test already exercises on decrypt.
            plaintext = decrypt_health_data(
                ciphertext=content,
                sender_private_key=our_key_material.get("private_key"),
                sender_nonce=our_key_material.get("nonce"),
                requester_public_key=hip_public_key_raw,
                requester_nonce=hip_key_material.get("nonce"),
            )
            bundle = json.loads(plaintext)
        except Exception as exc:
            log_error(f"Decryption failed for care context {care_context_reference}: {exc}")
            care_contexts[care_context_reference] = {
                "hi_status": "ERRORED",
                "description": f"Decryption failed: {exc}",
                "bundle": None,
                "received_at": generate_timestamp(),
            }
            continue

        # "OK", not "DELIVERED" -- confirmed via the M3 spec doc
        # (M3_Dcoument_16_02_2026_2319bac7bf.docx, section 5.3.3
        # "Notify"): the HIP's own hiStatus vocabulary is
        # [DELIVERED, ERRORED] (already correct in M2's own code),
        # but the HIU's is explicitly documented as [OK, ERRORED] --
        # a genuinely different vocabulary per role, not a typo to
        # unify. This was wrong in the original implementation
        # (used "DELIVERED" here) until cross-checked against this
        # doc section.
        care_contexts[care_context_reference] = {
            "hi_status": "OK",
            "description": "Received and decrypted successfully",
            "bundle": bundle,
            "received_at": generate_timestamp(),
        }

    return care_contexts


async def process_health_information_hiu_push(callback_data):
    """
    Confirmed inbound body shape (Postman collection, mirror image of
    M2's own send_health_information_data() payload):
        {"pageNumber": 0, "pageCount": 1, "transactionId": "...",
         "entries": [{"content": "...", "media": "application/fhir+json",
                       "checksum": "...", "careContextReference": "..."}],
         "keyMaterial": {"cryptoAlg": "ECDH", "curve": "Curve25519",
                          "dhPublicKey": {...}, "nonce": "..."}}

    For each entry: verifies the checksum (MD5 of entry["content"],
    matching _compute_checksum() above), then decrypts via
    fidelius_crypto.decrypt_health_data() using our own stored key
    material from step 1 (the pending session, looked up by
    transactionId) as one side of the ECDH exchange and this push
    payload's keyMaterial as the other. See
    server/fidelius_crypto.py's from_x509_public_key() docstring for why
    the HIP's incoming public key needs that conversion before use here.

    Stores the decrypted FHIR bundle (or failure reason) per
    careContextReference in hiu_health_information_repository.

    MULTI-PAGE HANDLING (added 2026-08-12, coupled to the M2 sender-side
    fix in health_information_request_service.py's _push_and_notify()):
    that function now pushes one care context per HTTP call (page_number
    incrementing, page_count = total care contexts in the transfer) so
    that each push can carry its own freshly generated keyMaterial
    instead of reusing one shared key across every entry (AES-GCM
    key+IV reuse -- see that function's own docstring for the full
    reasoning). That means MULTIPLE separate calls to this handler now
    arrive for one transactionId in the normal case (any transfer with
    more than one care context), not just in an edge case.

    Before this change, every push was treated as the complete,
    self-contained transaction: `save_hiu_health_information()` did a
    whole-record overwrite, and the notify call fired unconditionally at
    the end of every single push. Under the new one-push-per-page
    reality that would have silently discarded every page but the last
    one received, and sent ABDM a separate (and increasingly wrong,
    since each one only reflects a single entry) "transfer complete"
    notification per page instead of one for the whole transfer.

    Fixed by: (1) reading back whatever's already stored for this
    transactionId and merging this page's care_contexts into it rather
    than overwriting, and (2) only firing the notify once this page is
    the LAST one (pageNumber == pageCount - 1), at which point
    status_responses is built from the full merged set of care contexts
    across every page received so far, not just this page's single
    entry. A single-care-context transfer (page_count=1) behaves exactly
    as before -- it's always its own last page.

    Response to the HIP's POST is whatever dispatch_callback()'s
    standard success() returns ({"status": "OK"}, 200) -- same as every
    other callback route in this codebase (see server/callbacks/router.py).
    FLAGGED: no confirmed reference for what this specific response
    should look like; this is an assumption, consistent with the
    response shape already used everywhere else here.
    """
    try:
        log_phase("Encrypted records pushed directly by the HIP (POST /api/v3/hiu/health-information/push)")

        body = callback_data["body"]

        transaction_id = body.get("transactionId")
        entries = body.get("entries") or []
        hip_key_material = body.get("keyMaterial") or {}

        if not transaction_id:
            log_error("Data push payload missing transactionId -- cannot correlate to a pending health information request.")
            return

        pending = get_pending_health_information_request_by_transaction_id(transaction_id)

        if pending is None:
            log_error(f"No pending health information request found for transactionId {transaction_id}.")
            return

        our_key_material = pending.get("key_material") or {}
        consent_id = pending.get("consent_id")
        hip_id = pending.get("hip_id")
        hiu_id = pending.get("hiu_id")

        log_phase(f"Extracted {len(entries)} entrie(s) for transactionId {transaction_id}")

        # CONSENT-SCOPE CHECK (edge-case-review pass, tracker case M3-13):
        # before this fix, any careContextReference in a push's entries
        # was decrypted and stored unconditionally -- nothing here checked
        # that the care context was actually one of the ones consent_id
        # was ever granted for. A HIP (malicious, buggy, or just sending
        # stale data) could push a record for a patient/care context that
        # was never covered by this consent, and it would be accepted and
        # stored exactly like a legitimate one.
        #
        # The only source of truth for what a consent actually authorized
        # is the consent artefact we fetched and stored ourselves in
        # Block 1 (hiu_consent_repository, keyed by consentId -- see
        # consent_hiu_on_fetch_service.py). Its consent_detail is the raw
        # ABDM shape, carrying a top-level "careContexts" array of
        # {"patientReference", "careContextReference"} -- same field this
        # codebase already reads on the M2/HIP side in
        # consent_notify_service.py's save_consent() call. Any entry whose
        # careContextReference isn't in that set is rejected here (marked
        # ERRORED, not stored) rather than silently trusted.
        #
        # A missing/unfetched consent artefact is NOT treated as "allow
        # everything" -- if we never actually stored consent_id's detail,
        # we have no basis to say any care context is in scope, so every
        # entry in this push is rejected in that case too.
        stored_consent = get_hiu_consent(consent_id) if consent_id else None

        if stored_consent is None:
            authorized_care_context_refs = set()
            log_error(
                f"No stored consent artefact found for consentId={consent_id!r} -- "
                f"every entry in this push will be rejected as out-of-scope."
            )
        else:
            authorized_care_context_refs = {
                care_context.get("careContextReference")
                for care_context in (stored_consent.get("consent_detail") or {}).get("careContexts", [])
                if care_context.get("careContextReference")
            }

        # See from_x509_public_key()'s own docstring for why this
        # conversion is expected here (mirrors what our own M2 code sends
        # when IT pushes to an HIU's dataPushUrl -- certain for this
        # codebase's self-testing setup, since a push landing here in
        # practice comes from our own M2 code).
        try:
            hip_public_key_raw = from_x509_public_key(hip_key_material.get("dhPublicKey", {}).get("keyValue"))
        except Exception as exc:
            log_error(f"Could not decode HIP's public key for transactionId {transaction_id}: {exc}")
            hip_public_key_raw = None

        # Off the event loop thread (tracker case M2-5): decrypting a
        # push's entries is real CPU-bound work (RSA/ECDH + AES-GCM),
        # previously run directly inline in this async handler -- which
        # blocks the single uvicorn worker's event loop for however long
        # that takes, freezing every other in-flight request on this
        # server for the same duration. See discover_service.py's
        # process_discover() for the same pattern applied to blocking
        # requests.* calls; this is the equivalent fix for blocking CPU
        # work instead of blocking I/O.
        care_contexts = await asyncio.to_thread(
            _decrypt_entries,
            entries,
            authorized_care_context_refs,
            consent_id,
            hip_public_key_raw,
            our_key_material,
            hip_key_material,
        )

        page_number = body.get("pageNumber")
        page_count = body.get("pageCount")

        # MERGE, don't overwrite -- see this function's own docstring.
        # Each push (page) only carries the one/few care contexts for
        # that page; the stored record needs to accumulate across every
        # page seen so far for this transactionId, or every page but the
        # last would be silently destroyed the moment the next one
        # arrives.
        existing = get_hiu_health_information(transaction_id) or {}
        merged_care_contexts = dict(existing.get("care_contexts") or {})
        merged_care_contexts.update(care_contexts)

        save_hiu_health_information(
            transaction_id,
            {
                "consent_id": consent_id,
                "hip_id": hip_id,
                "page_number": page_number,
                "page_count": page_count,
                "care_contexts": merged_care_contexts,
            },
        )

        log_phase(
            f"Stored {len(care_contexts)} care context record(s) from this page "
            f"(page {page_number + 1 if page_number is not None else '?'}/{page_count or '?'}) -- "
            f"{len(merged_care_contexts)} total accumulated for transactionId {transaction_id}"
        )

        # Only notify ABDM once the LAST page for this transaction has
        # arrived -- a per-page notify would tell ABDM the transfer
        # "completed" after every single page, which is wrong once a
        # transfer spans more than one push. A page_count of None/1
        # (or a HIP that doesn't set these fields at all) is treated as
        # "this is the only/last page," matching the old one-push-per-
        # transaction behavior exactly.
        is_last_page = (
            page_count is None
            or page_number is None
            or page_number >= page_count - 1
        )

        if not is_last_page:
            log_waiting(
                f"Waiting for {page_count - page_number - 1} more page(s) before notifying ABDM "
                f"for transactionId {transaction_id}"
            )
            return

        # RECEIVED/FAILED (M3's own vocabulary, not M2's TRANSFERRED/
        # FAILED -- see send_health_information_notify()'s docstring).
        # Judgment call, not a confirmed ABDM behavior: any successfully
        # decrypted entry across the WHOLE transfer (all pages, not just
        # this one) counts the session as RECEIVED, even if other
        # entries failed -- there's no confirmed reference for
        # partial-failure semantics, and per-entry outcome is already
        # carried faithfully in status_responses either way.
        any_delivered_overall = any(
            result.get("hi_status") == "OK" for result in merged_care_contexts.values()
        )
        session_status = "RECEIVED" if any_delivered_overall else "FAILED"

        status_responses = [
            {
                "careContextReference": ref,
                "hiStatus": result["hi_status"],
                "description": result["description"],
            }
            for ref, result in merged_care_contexts.items()
        ]

        # Off the event loop thread -- see discover_service.py's
        # process_discover() for why every blocking requests.* call
        # reachable from an async def callback handler is wrapped this
        # way. Especially relevant here: this handler is itself the
        # deadlock-prone side of the M2<->M3 self-test loop (see
        # health_information_request_service.py's process_health_information_request()
        # for the confirmed deadlock this whole pass fixes).
        notify_response = await asyncio.to_thread(
            send_health_information_notify,
            consent_id=consent_id,
            transaction_id=transaction_id,
            hip_id=hip_id,
            done_at=generate_safe_past_timestamp(),
            session_status=session_status,
            status_responses=status_responses,
            notifier_type="HIU",
            notifier_id=hiu_id,
        )

        log_api_call("Notifying ABDM of Receipt Outcome", "POST .../health-information/notify", notify_response.status_code)

        if notify_response.status_code != 202:
            print_api_response(notify_response)

        if session_status == "RECEIVED":
            log_phase("Records received and decrypted -- Block 2 complete for this transaction.")
        else:
            log_error("No records were successfully received/decrypted for this transaction -- see status responses above")

    except Exception as exc:
        log_error(f"Health Information push callback processing failed unexpectedly: {exc}")
        return
