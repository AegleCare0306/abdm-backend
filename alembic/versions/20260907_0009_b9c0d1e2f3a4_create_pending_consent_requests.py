"""create pending_consent_requests

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-09-07

P17 -- repo/'s Postgres-backed replacement for
storage/pending_consent_requests.jsonl (main table -- see the next
migration for its index-table sibling). See
server/callbacks/repository/pending_consent_request_repository.py and
server/db_models.py:PendingConsentRequest.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_consent_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_pending_consent_requests"),
        sa.UniqueConstraint("request_id", name="uq_pending_consent_requests_request_id"),
    )


def downgrade() -> None:
    op.drop_table("pending_consent_requests")
