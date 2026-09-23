"""
JWT verification for inbound ABDM callbacks.

CRITICAL, flagged in an edge-case review: every callback route in
server/callbacks/router.py received an unauthenticated POST before this
module existed -- anyone who discovered or guessed a callback URL could
send a fabricated payload and have it processed as if ABDM sent it,
despite every genuine ABDM callback carrying a real Keycloak-issued
bearer JWT. This module verifies that JWT (signature, iss, exp, and a
sanity check on aud/azp -- see below) before a callback route's body (and
therefore dispatch_callback()) ever runs, wired in as one shared FastAPI
dependency (Depends(verify_abdm_callback), applied via each route's own
`dependencies=[...]` in router.py) rather than copy-pasted per handler.

JWKS ENDPOINT -- CONFIRMED LIVE, 2026-08-12, not guessed:
    https://dev.abdm.gov.in/auth/realms/central-registry/protocol/openid-connect/certs
The saved "ABDM - Milestone 2" Postman collection's own "Keycloak
Certificate API" request (https://dev.abdm.gov.in/api/hiecm/gateway/v3/certs)
turned out to be WRONG for this purpose -- hit live, it 401s
(WWW-Authenticate: Basic realm="Realm"), a gateway-proxied path that
isn't the real Keycloak JWKS endpoint (same 401 for the collection's
"OpenID Configuration API" request under that same gateway-proxied
prefix). The real, working endpoint was confirmed two independent ways:
(1) every real captured token's own iss claim is
https://dev.abdm.gov.in/auth/realms/central-registry (2) the standard,
unauthenticated OIDC discovery document at
{iss}/.well-known/openid-configuration -- a different host path than the
gateway-proxied one above -- explicitly gives
"jwks_uri": "https://dev.abdm.gov.in/auth/realms/central-registry/protocol/openid-connect/certs",
and hitting that URL live returns a real JWK Set (2 RSA keys as of this
writing: kid=AlRb5WCm8Tm9EJ_IfO9z06j9oCv51pKKFknGb_TBvK0 alg=RS256, and
kid=oc-l6O1yJ7wJKYEeyeUafsz3Aecq7YnCIqbzbIfkJk8 alg=RS512).

CLAIM VERIFICATION -- iss/aud/azp, evidence-based (deviates from the
original ask's literal wording -- flagged explicitly in the change
report, not silently decided): decoded (unverified, signature not yet
checked) every one of the 168 real Bearer JWTs found across every
captured inbound callback in storage/callbacks/*.json:
  - iss: 100% consistent (168/168) -- always the real Keycloak realm
    above. Hard-verified via jwt.decode(..., issuer=ABDM_ISSUER).
  - azp: always present (168/168), but NOT always "gateway" -- 157/168
    are azp="gateway" (ABDM's own gateway service account calling us),
    the other 11/168 are azp=<our own sandbox CLIENT_ID,
    server/config.py>. Real explanation, not a data artifact: this
    codebase runs BOTH the M2 HIP role and the M3 HIU role on one server
    for sandbox self-testing (see server/callbacks/services/
    health_information_request_service.py's own deadlock-fix history,
    2026-08-11, for the same self-referential M2<->M3 push pattern) --
    those 11 are genuine, legitimate self-push callbacks where WE
    generated the Authorization header ourselves (get_gateway_token(),
    using our own client credentials) and then received it back at our
    own callback endpoint. Hard-requiring azp=="gateway" (the literal
    original ask) would silently break that real, currently-working
    flow. Verified instead as: azp must be present AND be one of
    {"gateway", CLIENT_ID}.
  - aud: present ("account") in 157/168, ABSENT entirely in the same
    11 self-push tokens -- Keycloak's client_credentials response for
    our own sandbox client apparently doesn't set aud the way the real
    gateway service account's token does. Hard-requiring aud=="account"
    would break the same self-push flow. Verified instead as: IF
    present, must equal "account"; absent is accepted (matches confirmed
    legitimate traffic, not just "gave up checking").
These two relaxations do not weaken the actual security boundary this
module exists for. An attacker with no real ABDM/Keycloak credentials
cannot produce a validly-signed token carrying ANY azp/aud value,
whatever they choose to claim, since they don't have ABDM's private
signing key. Signature + iss + exp are what actually stop the
fabricated-payload attack; azp/aud are supplementary sanity checks,
relaxed here based on real evidence rather than left strict and silently
breaking real traffic the very first time this ran for real.

CACHING: PyJWKClient's own get_signing_key(kid) is wrapped in an
lru_cache keyed by kid (see _jwks_client below) -- a kid already seen
is served from memory with no network call; a kid not yet seen (e.g.
immediately after ABDM rotates its signing keys) is always a fresh JWKS
fetch, never a stale/failed-closed cache entry for the process's
lifetime. This is PyJWT's own built-in behavior, not custom code here.
"""

import asyncio
import json
import os
import urllib.request

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError
from fastapi import Request, HTTPException

from server.config import CLIENT_ID
from server.callbacks.utils.flow_logger import log_error

ABDM_ISSUER = "https://dev.abdm.gov.in/auth/realms/central-registry"
ABDM_JWKS_URL = f"{ABDM_ISSUER}/protocol/openid-connect/certs"

# Confirmed live 2026-08-12 against the real JWKS above -- the exact
# algorithms ABDM's realm currently advertises (RS256 and RS512, one key
# each). Passed explicitly to jwt.decode()'s own algorithms= allowlist --
# never derived from the token's own header alg alone -- to guard against
# algorithm-confusion attacks (e.g. an attacker claiming alg="none" or
# alg="HS256" using our own RSA public key as an HMAC secret).
ALLOWED_ALGORITHMS = ["RS256", "RS512"]

ALLOWED_AUDIENCE = "account"

# EXTENSIBLE PER ENVIRONMENT (2026-09-22). Beyond "gateway" and our own
# CLIENT_ID, ABDM turns out to use further service accounts for some
# callback families: its Health Locker callbacks arrive signed correctly
# by ABDM's Keycloak but carrying azp="TEST_PHR" on the sandbox, and were
# rejected 401 until this existed (found live via aegle-phr's own P19
# locker work -- the same fix is in aegle-abdm-core's callback_auth.py,
# which is where aegle_phr's own callback routes are gated).
#
# Kept as an env var with an EMPTY default, so with nothing configured
# this file behaves exactly as it always has. "TEST_PHR" is a sandbox
# account name and does not belong hardcoded in either codebase.
#
# Does not weaken the boundary: signature, iss and exp are all verified
# against ABDM's live JWKS BEFORE azp is inspected (see _verify_token()),
# so no caller lacking ABDM's signing key can present any azp at all.
EXTRA_ALLOWED_AZP = {
    value.strip()
    for value in (os.environ.get("EXTRA_ALLOWED_AZP") or "").split(",")
    if value.strip()
}
ALLOWED_AZP_VALUES = {"gateway", CLIENT_ID} | EXTRA_ALLOWED_AZP


class _TimeoutPyJWKClient(PyJWKClient):
    """
    PyJWT 2.3.0's PyJWKClient.fetch_data() calls urllib.request.urlopen()
    with no timeout -- exactly the class of blocking-call-with-no-timeout
    issue fixed everywhere else in server/ for outbound requests.* calls
    (2026-08-11, timeout=30 added to every call site). Overridden here
    the same way and for the same reason: a hung/unreachable JWKS
    endpoint must not be able to tie up a worker thread indefinitely.
    """

    def fetch_data(self):
        with urllib.request.urlopen(self.uri, timeout=30) as response:
            return json.load(response)


# Module-level singleton so the kid-keyed signing-key cache (see this
# module's own docstring, CACHING) persists for the server process's
# whole lifetime, not just one request -- "don't refetch on every
# request" per the original ask.
_jwks_client = _TimeoutPyJWKClient(ABDM_JWKS_URL)


class AbdmJwtVerificationError(Exception):
    """
    Raised by _verify_token() for any verification failure -- caught by
    verify_abdm_callback() and turned into a 401. Kept as one common
    exception type (not per-failure-mode subclasses) since every caller
    here only ever needs "verification failed, reject the request" plus
    a human-readable reason for logging; no caller branches on failure
    type.
    """


def _verify_token(token):
    """
    The actual JWT verification -- synchronous and blocking (PyJWT and
    PyJWKClient are neither async-aware), which is why every caller of
    this function goes through asyncio.to_thread() (see
    verify_abdm_callback()'s own docstring). Raises
    AbdmJwtVerificationError on any failure; returns the decoded claims
    dict on success.
    """
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
    except PyJWKClientError as exc:
        raise AbdmJwtVerificationError(f"Could not resolve a signing key for this token: {exc}")
    except Exception as exc:
        raise AbdmJwtVerificationError(f"Malformed token or JWKS fetch/lookup failed: {exc}")

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=ALLOWED_ALGORITHMS,
            issuer=ABDM_ISSUER,
            # aud is checked manually below, not via PyJWT's own
            # verify_aud -- see this module's docstring (CLAIM
            # VERIFICATION) for why "must equal 'account' if present,
            # but absent is also acceptable" isn't expressible through
            # PyJWT's audience= parameter (passing it would reject
            # every token that lacks aud entirely; omitting it makes
            # PyJWT reject every token that HAS aud instead -- see
            # PyJWT's own _validate_aud()).
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise AbdmJwtVerificationError("Token has expired")
    except jwt.InvalidIssuerError:
        raise AbdmJwtVerificationError("Token iss claim does not match ABDM's Keycloak realm")
    except jwt.InvalidTokenError as exc:
        raise AbdmJwtVerificationError(f"Token signature/claims invalid: {exc}")

    azp = claims.get("azp")
    if azp not in ALLOWED_AZP_VALUES:
        raise AbdmJwtVerificationError(f"Unexpected azp claim: {azp!r}")

    aud = claims.get("aud")
    if aud is not None and aud != ALLOWED_AUDIENCE:
        raise AbdmJwtVerificationError(f"Unexpected aud claim: {aud!r}")

    return claims


async def verify_abdm_callback(request: Request):
    """
    Shared FastAPI dependency -- wired into every inbound-callback route
    in server/callbacks/router.py via `dependencies=[Depends(verify_abdm_callback)]`,
    so verification is applied consistently in one place rather than
    copy-pasted per handler. Runs BEFORE the route body (and therefore
    before dispatch_callback()), so a rejected request never reaches
    application logic and gets a real 401 -- not silently swallowed and
    disguised as ABDM's usual 200 success() ack, which is the response
    dispatch_callback()'s own error handling gives for a genuine
    processing failure (a deliberately different case: this module's
    401 means "we don't believe this request came from ABDM at all,"
    not "something went wrong handling a request that did").

    The actual verification (_verify_token()) is synchronous and can
    make a real blocking network call on a JWKS cache miss (the first
    request ever, or right after ABDM rotates its signing keys) -- run
    via asyncio.to_thread() so a slow/stuck JWKS fetch can never block
    this server's event loop, matching the convention already
    established in server/ for exactly this class of bug (2026-08-11).
    """
    auth_header = request.headers.get("authorization")

    if not auth_header or not auth_header.strip().lower().startswith("bearer "):
        log_error(f"Rejected callback to {request.url.path}: missing or malformed Authorization header")
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    token = auth_header.strip()[7:].strip()

    try:
        await asyncio.to_thread(_verify_token, token)
    except AbdmJwtVerificationError as exc:
        log_error(f"Rejected callback to {request.url.path}: {exc}")
        raise HTTPException(status_code=401, detail="Invalid bearer token")
