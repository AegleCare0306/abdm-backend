"""
Alembic environment for repo/'s own three security-critical repository
tables (P16). Independent of aegle-phr/alembic/env.py -- see alembic.ini's
own header comment for why two separate Alembic chains against the same
Postgres instance is fine here.

The database URL comes from server.config.DATABASE_URL (i.e. repo/.env via
python-dotenv), never from alembic.ini -- see that file's own header
comment. This module runs as an Alembic CLI entry point, so reading config
at module scope is correct here.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from server.config import DATABASE_URL
from server.db_models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Injected from server.config rather than read from alembic.ini.
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Autogenerate compares against this.
target_metadata = Base.metadata


# P16 -- this chain shares its actual database with aegle-phr/alembic's own
# chain (both point at the same Postgres instance/db, see this module's own
# docstring), but Alembic tracks "current revision" in a single
# alembic_version table BY DEFAULT, with no awareness of separate migration
# directories -- confirmed live: running `alembic upgrade head` here against
# a database that already had aegle-phr's own alembic_version row failed
# with "Can't locate revision identified by <aegle-phr's own latest rev>",
# because this chain's own versions/ directory has no idea that revision
# even exists. version_table below gives this chain its OWN separate
# tracking table (alembic_version_repo, vs. aegle-phr's default
# alembic_version) so the two chains' "what's the current revision" state
# never collides, even though both create real tables in the same database.
_VERSION_TABLE = "alembic_version_repo"


# SAME sharing situation as _VERSION_TABLE above, but for autogenerate
# specifically -- found live, the hard way (2026-09-07): `alembic revision
# --autogenerate` reflects the ENTIRE live database (every table in the
# `public` schema, regardless of which Alembic chain owns it) and diffs
# that against this chain's OWN target_metadata. Any table this chain
# doesn't define -- i.e. every one of aegle-phr's own tables
# (callback_log, abdm_call_log, subscription_request, uil_link_request)
# -- looked like something that SHOULD be dropped, and the first
# autogenerate run here produced a migration that would have destroyed
# all four of them. Caught before ever running `alembic upgrade head` on
# it, not after. include_name below tells autogenerate to only ever
# consider tables this chain's own metadata actually defines when
# reflecting the live database for comparison -- anything else (a table,
# or an index/constraint belonging to one) is invisible to the diff
# entirely, so it can never again be proposed for a drop just because a
# DIFFERENT chain owns it.
def _include_name(name, type_, parent_names):
    if type_ == "table":
        return name is None or name in target_metadata.tables
    return True


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (`alembic upgrade head --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=_VERSION_TABLE,
        include_name=_include_name,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and run migrations against the live database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=_VERSION_TABLE,
            include_name=_include_name,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
