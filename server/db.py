"""
Database engine and session handling for repo/'s own three security-
critical repository modules (hiu_consent_repository.py,
consent_repository.py, patient_identity_repository.py -- P16).

MIRRORS aegle_phr/db.py's proven pattern, DOES NOT IMPORT IT. server/
main.py's own comment is explicit: aegle-phr and aegle-abdm-core "must not
become hard dependencies" of repo/, wrapped in try/except specifically so
repo/ still runs standalone without either installed. Reusing
aegle_phr.db's already-bootstrapped engine would violate that outright --
and tools/m3_test_suite/common.py calls these repositories as a standalone
CLI script that never goes through aegle_phr's bootstrap at all, so it
couldn't reach that engine even if the dependency were acceptable. This
file is a small, self-contained copy of the pattern instead.

SYNC, NOT ASYNC, same reasoning aegle_phr/db.py's own docstring gives:
every route handler in this codebase is a plain `def` (server/main.py,
server/callbacks/router.py), so a blocking psycopg call inside one runs on
FastAPI's own threadpool, which is where blocking work belongs -- an
`async def` handler making a blocking DB call would stall the event loop
for every other request in the process, exactly the bug this project's own
commit 6a1d748 already found and fixed once for M2/M3's data push.

NO ENGINE IS CREATED AT IMPORT. init_engine() is called explicitly (from
server/main.py at startup, and from tools/m3_test_suite/common.py for the
standalone CLI) and is idempotent -- calling it twice in the same process
must not open a second connection pool.
"""

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None

# libpq connect_timeout, in seconds -- same value and same reasoning as
# aegle_phr/db.py's own constant: without this, an unreachable database
# does not fail fast (measured there at roughly four minutes before giving
# up), which would make GET /health useless and stall a threadpool worker
# on every request touching one of these three repositories while Postgres
# is down.
_CONNECT_TIMEOUT_SECONDS = 5


def init_engine(database_url: str, echo: bool = False) -> Engine:
    """
    Creates the process-wide engine and session factory, once.

    IDEMPOTENT: if an engine already exists it is returned unchanged and
    `database_url` is ignored -- callers that genuinely need to point at a
    different database (tests) must call reset_engine() first.
    """
    global _engine, _session_factory

    if _engine is not None:
        return _engine

    _engine = create_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
        future=True,
        connect_args={"connect_timeout": _CONNECT_TIMEOUT_SECONDS},
    )
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    """
    The engine created by init_engine().

    Raises:
        RuntimeError: If init_engine() was never called -- a loud,
            explicit error naming the fix, rather than a None dereference
            deep inside a repository call.
    """
    if _engine is None:
        raise RuntimeError(
            "repo/'s database engine is not initialised. Call "
            "server.db.init_engine(DATABASE_URL) once at process startup "
            "(server/main.py does this already; a standalone script "
            "touching hiu_consent_repository/consent_repository/"
            "patient_identity_repository must do it too -- see "
            "tools/m3_test_suite/common.py for the reference call site)."
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """The session factory created by init_engine(). Raises if uninitialised."""
    if _session_factory is None:
        get_engine()  # raises the explanatory RuntimeError
    assert _session_factory is not None
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """
    Transactional scope around a series of operations. Commits on clean
    exit, rolls back on any exception, always closes.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_connection() -> bool:
    """
    True if the database answers a trivial query. Never raises -- this
    backs GET /health, which must report a down database as
    `"database": false` rather than failing the health check itself with
    a 500 (a health endpoint that 500s tells a load balancer nothing it
    can distinguish from the app being wedged).
    """
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def reset_engine() -> None:
    """
    Disposes the engine and clears both slots. For tests; not something a
    normal run needs to call.
    """
    global _engine, _session_factory

    if _engine is not None:
        _engine.dispose()

    _engine = None
    _session_factory = None
