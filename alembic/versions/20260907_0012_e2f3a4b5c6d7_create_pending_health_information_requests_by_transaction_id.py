"""create pending_health_information_requests_by_transaction_id

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-07

P17 -- repo/'s Postgres-backed replacement for
storage/pending_health_information_requests_by_transaction_id.jsonl --
the index table for pending_health_information_requests (ABDM's
transactionId -> our own REQUEST-ID). `request_id` is a plain text
column, NOT JSONB -- the old index file's own stored value was a bare
string, not a JSON object. See
server/callbacks/repository/pending_health_information_request_repository.py
and server/db_models.py:PendingHealthInformationRequestByTransactionId.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_health_information_requests_by_transaction_id",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("transaction_id", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_pending_health_information_requests_by_transaction_id"),
        sa.UniqueConstraint(
            "transaction_id", name="uq_pending_health_information_requests_by_transaction_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("pending_health_information_requests_by_transaction_id")
