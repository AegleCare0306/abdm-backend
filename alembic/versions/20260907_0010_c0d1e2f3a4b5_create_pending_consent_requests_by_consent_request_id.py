"""create pending_consent_requests_by_consent_request_id

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-09-07

P17 -- repo/'s Postgres-backed replacement for
storage/pending_consent_requests_by_consent_request_id.jsonl -- the index
table for pending_consent_requests (consentRequestId -> our own
REQUEST-ID). `request_id` is a plain text column, NOT JSONB -- the old
index file's own stored value was a bare string, not a JSON object. See
server/callbacks/repository/pending_consent_request_repository.py and
server/db_models.py:PendingConsentRequestByConsentRequestId.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_consent_requests_by_consent_request_id",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("consent_request_id", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_pending_consent_requests_by_consent_request_id"),
        sa.UniqueConstraint(
            "consent_request_id", name="uq_pending_consent_requests_by_consent_request_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("pending_consent_requests_by_consent_request_id")
