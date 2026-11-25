"""plan free extension flag

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("test_plans", sa.Column("extended", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("test_plans", "extended")
