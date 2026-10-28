"""meal plan, pantry, recipe gallery, step photos, public links

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-29
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Только ADD COLUMN и индекс: пересоздание таблицы recipes в SQLite (batch) при включённых
    # внешних ключах стёрло бы каскадом ингредиенты и шаги
    op.add_column("recipes", sa.Column("share_token", sa.String(32), nullable=True))
    op.create_index("ix_recipes_share_token", "recipes", ["share_token"], unique=True)
    op.add_column("recipe_steps", sa.Column("image", sa.String(64), nullable=True))

    op.create_table(
        "recipe_photos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recipe_id", sa.Integer(), sa.ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("image", sa.String(64), nullable=False),
    )
    op.create_index("ix_recipe_photos_recipe_id", "recipe_photos", ["recipe_id"])

    op.create_table(
        "meal_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("slot", sa.String(16), nullable=False, server_default="dinner"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recipe_id", sa.Integer(), sa.ForeignKey("recipes.id", ondelete="CASCADE"), nullable=True),
        sa.Column("servings", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_meal_plan_owner_id", "meal_plan", ["owner_id"])
    op.create_index("ix_meal_plan_day", "meal_plan", ["day"])
    op.create_index("ix_meal_plan_recipe_id", "meal_plan", ["recipe_id"])

    op.create_table(
        "meal_plan_members",
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "pantry",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("pantry")
    op.drop_table("meal_plan_members")
    op.drop_table("meal_plan")
    op.drop_table("recipe_photos")
    op.drop_index("ix_recipes_share_token", "recipes")
    with op.batch_alter_table("recipe_steps") as batch:
        batch.drop_column("image")
    with op.batch_alter_table("recipes") as batch:
        batch.drop_column("share_token")
