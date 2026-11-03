"""prices, recipe cost snapshots, product aliases

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

MYSQL = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


def upgrade() -> None:
    # Цены продуктов: каждая покупка — новая строка, в расчёт идёт последняя на дату
    op.create_table(
        "product_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("package_amount", sa.Float(), nullable=False),
        sa.Column("package_unit", sa.String(16), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        **MYSQL,
    )
    op.create_index("ix_product_prices_product_id", "product_prices", ["product_id"])

    # Снимки себестоимости рецепта — история для графика «как дорожал»
    op.create_table(
        "recipe_cost_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recipe_id", sa.Integer(), sa.ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total", sa.Float(), nullable=False),
        sa.Column("per_serving", sa.Float(), nullable=False),
        sa.Column("priced_count", sa.Integer(), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        # {product_id: стоимость} — чтобы понять, что именно подорожало
        sa.Column("lines_json", sa.Text(), nullable=False),
        **MYSQL,
    )
    op.create_index("ix_recipe_cost_snapshots_recipe_id", "recipe_cost_snapshots", ["recipe_id"])

    # Синонимы продуктов: старые имена после объединения дублей
    op.create_table(
        "product_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alias", sa.String(128), nullable=False, unique=True),
        sa.Column("match_key", sa.String(128), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        **MYSQL,
    )
    op.create_index("ix_product_aliases_match_key", "product_aliases", ["match_key"])
    op.create_index("ix_product_aliases_product_id", "product_aliases", ["product_id"])


def downgrade() -> None:
    op.drop_table("product_aliases")
    op.drop_table("recipe_cost_snapshots")
    op.drop_table("product_prices")
