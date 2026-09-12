"""create pending_health_information_requests

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-09-07

P17 -- repo/'s Postgres-backed replacement for
storage/pending_health_information_requests.jsonl (main table -- see the
next migration for its index-table sibling). See
server/callbacks/repository/pending_health_information_request_repository.py
and server/db_models.py:PendingHealthInformationRequest.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_health_information_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_pending_health_information_requests"),
        sa.UniqueConstraint("request_id", name="uq_pending_health_information_requests_request_id"),
    )


def downgrade() -> None:
    op.drop_table("pending_health_information_requests")
