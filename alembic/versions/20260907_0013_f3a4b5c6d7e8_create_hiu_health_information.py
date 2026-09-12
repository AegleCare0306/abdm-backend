"""create hiu_health_information

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-09-07

P17 -- repo/'s Postgres-backed replacement for
storage/hiu_health_information.jsonl. See
server/callbacks/repository/hiu_health_information_repository.py and
server/db_models.py:HiuHealthInformation. NOTE: the source file was
14.9 MB across only 118 live keys (~127 KB average payload -- full FHIR
bundles) -- Postgres JSONB handles this with no special handling (TOAST
storage is automatic).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hiu_health_information",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("transaction_id", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_hiu_health_information"),
        sa.UniqueConstraint("transaction_id", name="uq_hiu_health_information_transaction_id"),
    )


def downgrade() -> None:
    op.drop_table("hiu_health_information")
