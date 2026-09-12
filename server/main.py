import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.callbacks.router import router as callback_router
from server.config import DATABASE_URL
from server.db import check_connection, init_engine
from typing import Dict

# P16 -- initialises repo/'s OWN engine (server/db.py), independent of
# aegle_phr's below. Must happen before any request can reach
# hiu_consent_repository.py/consent_repository.py/patient_identity_
# repository.py, which now require it (server/db.py's own get_engine()
# raises a clear RuntimeError otherwise, rather than a request silently
# failing later). This is a real, deliberate change to this backend's
# standalone story -- it did not need any external service to start up
# correctly before this; see server/db.py's own module docstring.
init_engine(DATABASE_URL)

# The PHR app (aegle-phr) mounts INTO this process, because there is only
# one ngrok static domain and it points here, at port 8000. Wrapped in
# try/except so this backend still runs standalone on a machine that has
# not installed aegle-phr / aegle-abdm-core -- those must not become hard
# dependencies of a working, sandbox-tested service.
try:
    from aegle_phr.bootstrap import bootstrap as phr_bootstrap
    from aegle_phr.api import build_router as phr_build_router
    from aegle_phr.settings import load_settings as phr_load_settings
except ImportError:
    phr_bootstrap = None

app = FastAPI(
    title="ABDM Sandbox API",
    version="1.0.0"
)

# The test UI is served from another origin (Vercel), so it needs CORS here
# too. Wildcard is deliberate for this sandbox harness -- the PHR app API's
# X-Aegle-Key header is the actual access control. Narrow before anything real.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(callback_router)

if phr_bootstrap is not None:
    _phr_settings = phr_load_settings()
    phr_bootstrap(_phr_settings)
    app.include_router(phr_build_router(_phr_settings))
    logging.getLogger("uvicorn.error").info("PHR app mounted (aegle_phr).")
else:
    logging.getLogger("uvicorn.error").warning(
        "aegle_phr not installed -- PHR routes are NOT mounted. "
        "This backend is running standalone."
    )

@app.get("/")
def home():
    return {"message": "Hello from my ABDM Backend!"}


@app.get("/health")
def health():
    # P16 -- reports the new DB dependency's own reachability rather than
    # failing this endpoint outright if it's down (check_connection()
    # never raises, see server/db.py's own docstring) -- a health check
    # that 500s tells a load balancer nothing it can distinguish from the
    # app being wedged.
    return {"status": "healthy", "database": check_connection()}


@app.post("/echo")
def echo(data: Dict):
    return {
        "received": data
    }