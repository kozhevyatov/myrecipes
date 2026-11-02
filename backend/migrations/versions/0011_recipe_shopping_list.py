"""shopping list per recipe

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Без внешнего ключа: в SQLite его нельзя добавить без пересоздания таблицы;
    # при удалении рецепта ссылку обнуляет код
    op.add_column("shopping_lists", sa.Column("recipe_id", sa.Integer(), nullable=True))
    op.create_index("ix_shopping_lists_recipe_id", "shopping_lists", ["recipe_id"])


def downgrade() -> None:
    op.drop_index("ix_shopping_lists_recipe_id", "shopping_lists")
    with op.batch_alter_table("shopping_lists") as batch:
        batch.drop_column("recipe_id")
