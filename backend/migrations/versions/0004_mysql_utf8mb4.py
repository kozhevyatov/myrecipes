"""MySQL/MariaDB: перевести базу и таблицы в utf8mb4 (эмодзи в рецептах)

Если базу создали с кодировкой по умолчанию (latin1 / utf8mb3), сохранение
текста с эмодзи падает с «Incorrect string value». Для SQLite миграция ничего не делает.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABLES = [
    "users",
    "app_settings",
    "categories",
    "tags",
    "products",
    "recipes",
    "recipe_tags",
    "recipe_ingredients",
    "recipe_steps",
    "alembic_version",
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in ("mysql", "mariadb"):
        return
    db_name = bind.execute(sa.text("SELECT DATABASE()")).scalar()
    if db_name:
        op.execute(f"ALTER DATABASE `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    # Внешние ключи мешают менять кодировку связанных столбцов — временно отключаем проверку
    op.execute("SET FOREIGN_KEY_CHECKS=0")
    try:
        for table in TABLES:
            op.execute(f"ALTER TABLE `{table}` CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    finally:
        op.execute("SET FOREIGN_KEY_CHECKS=1")


def downgrade() -> None:
    pass
