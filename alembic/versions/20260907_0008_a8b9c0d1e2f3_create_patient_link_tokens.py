"""create patient_link_tokens

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-09-07

P17 -- repo/'s Postgres-backed replacement for
storage/patient_link_tokens.jsonl. See
server/callbacks/repository/patient_link_token_repository.py and
server/db_models.py:PatientLinkToken. `composite_key` holds the same
"{abha_address}|{hip_id}" string the file-backed version used as its
single key -- kept as one column on purpose, see that module's own
docstring.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "patient_link_tokens",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("composite_key", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_patient_link_tokens"),
        sa.UniqueConstraint("composite_key", name="uq_patient_link_tokens_composite_key"),
    )


def downgrade() -> None:
    op.drop_table("patient_link_tokens")
