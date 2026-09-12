"""create pending_care_context_notifies

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-07

P17 -- repo/'s Postgres-backed replacement for
storage/pending_care_context_notifies.jsonl. See
server/callbacks/repository/care_context_notify_repository.py and
server/db_models.py:PendingCareContextNotify.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_care_context_notifies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_pending_care_context_notifies"),
        sa.UniqueConstraint("request_id", name="uq_pending_care_context_notifies_request_id"),
    )


def downgrade() -> None:
    op.drop_table("pending_care_context_notifies")
