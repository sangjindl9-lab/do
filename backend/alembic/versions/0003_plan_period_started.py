"""plan period started flag

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("test_plans", sa.Column("period_started", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("test_plans", "period_started")
