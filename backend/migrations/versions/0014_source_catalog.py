"""Persistent external recipe catalog and source refresh preferences.

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None
MYSQL = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


def upgrade() -> None:
    op.add_column("import_sources", sa.Column("visible_in_catalog", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("import_sources", sa.Column("auto_refresh", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("import_sources", sa.Column("refresh_interval_hours", sa.Integer(), nullable=False, server_default="24"))
    op.add_column("import_sources", sa.Column("refresh_author_id", sa.Integer(), nullable=True))
    op.add_column("import_sources", sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("import_sources", sa.Column("next_refresh_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("import_sources", sa.Column("index_complete", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("import_sources", sa.Column("index_error", sa.String(2000), nullable=False, server_default=""))
    op.add_column("import_sources", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "source_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("import_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("parent_url", sa.Text(), nullable=True),
        sa.UniqueConstraint("source_id", "url_hash", name="uq_source_category_url"),
        **MYSQL,
    )
    op.create_index("ix_source_categories_source_id", "source_categories", ["source_id"])
    op.create_table(
        "source_recipes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("import_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("source_categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("url_hash", sa.String(64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.Text().with_variant(mysql.LONGTEXT(), "mysql", "mariadb"), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("source_id", "url_hash", name="uq_source_recipe_url"),
        **MYSQL,
    )
    op.create_index("ix_source_recipes_source_id", "source_recipes", ["source_id"])
    op.create_index("ix_source_recipes_category_id", "source_recipes", ["category_id"])
    op.create_table(
        "source_recipe_imports",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_recipe_id", sa.Integer(), sa.ForeignKey("source_recipes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("recipe_id", sa.Integer(), sa.ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False),
        **MYSQL,
    )
    op.create_index("ix_source_recipe_imports_recipe_id", "source_recipe_imports", ["recipe_id"])


def downgrade() -> None:
    op.drop_table("source_recipe_imports")
    op.drop_table("source_recipes")
    op.drop_table("source_categories")
    for name in ("deleted_at", "index_error", "index_complete", "next_refresh_at", "last_indexed_at", "refresh_author_id",
                 "refresh_interval_hours", "auto_refresh", "visible_in_catalog"):
        op.drop_column("import_sources", name)
