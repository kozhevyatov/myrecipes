"""product nutrition (КБЖУ на 100 г, вес штуки, плотность)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

COLUMNS = ["kcal", "protein", "fat", "carbs", "piece_grams", "density"]


def upgrade() -> None:
    with op.batch_alter_table("products") as batch:
        for col in COLUMNS:
            batch.add_column(sa.Column(col, sa.Float(), nullable=True))
        batch.add_column(sa.Column("nutrition_source", sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("products") as batch:
        batch.drop_column("nutrition_source")
        for col in reversed(COLUMNS):
            batch.drop_column(col)
