"""recipe source url

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("recipes") as batch:
        batch.add_column(sa.Column("source_url", sa.String(500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("recipes") as batch:
        batch.drop_column("source_url")
