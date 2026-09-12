"""create health_information_sessions

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-09-07

P17 -- repo/'s Postgres-backed replacement for
server/callbacks/repository/health_information_repository.py's own
`_health_information_sessions` module-level dict. UNLIKE every other
table in this chain, this one replaces an IN-MEMORY store, not a file --
nothing to backfill (the dict is always empty at migration time). See
server/db_models.py:HealthInformationSession and that repository
module's own docstring for the JSONB `||` partial-merge requirement this
table's data column is used with.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "health_information_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("transaction_id", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_health_information_sessions"),
        sa.UniqueConstraint("transaction_id", name="uq_health_information_sessions_transaction_id"),
    )


def downgrade() -> None:
    op.drop_table("health_information_sessions")
