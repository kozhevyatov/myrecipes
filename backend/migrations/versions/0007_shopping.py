"""shopping list

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shopping_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(32), nullable=False, server_default=""),
        sa.Column("note", sa.String(300), nullable=False, server_default=""),
        sa.Column("checked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_shopping_items_user_id", "shopping_items", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_shopping_items_user_id", table_name="shopping_items")
    op.drop_table("shopping_items")
