"""several shopping lists with sharing

Текущие пункты каждого пользователя переносятся в его список «Покупки».

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-28
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shopping_lists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_shopping_lists_owner_id", "shopping_lists", ["owner_id"])
    op.create_table(
        "shopping_list_members",
        sa.Column("list_id", sa.Integer(), sa.ForeignKey("shopping_lists.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    )

    with op.batch_alter_table("shopping_items") as batch:
        batch.add_column(sa.Column("list_id", sa.Integer(), nullable=True))

    # Перенос: у каждого, у кого есть пункты, появляется список «Покупки»
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    lists = sa.table(
        "shopping_lists",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("owner_id", sa.Integer),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    user_ids = [r[0] for r in bind.execute(sa.text("SELECT DISTINCT user_id FROM shopping_items"))]
    for uid in user_ids:
        bind.execute(lists.insert().values(name="Покупки", owner_id=uid, created_at=now, updated_at=now))
        list_id = bind.execute(
            sa.text("SELECT MAX(id) FROM shopping_lists WHERE owner_id = :u"), {"u": uid}
        ).scalar()
        bind.execute(sa.text("UPDATE shopping_items SET list_id = :l WHERE user_id = :u"), {"l": list_id, "u": uid})

    with op.batch_alter_table("shopping_items") as batch:
        batch.alter_column("list_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            "fk_shopping_items_list_id", "shopping_lists", ["list_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_index("ix_shopping_items_list_id", ["list_id"])


def downgrade() -> None:
    with op.batch_alter_table("shopping_items") as batch:
        batch.drop_index("ix_shopping_items_list_id")
        batch.drop_constraint("fk_shopping_items_list_id", type_="foreignkey")
        batch.drop_column("list_id")
    op.drop_table("shopping_list_members")
    op.drop_index("ix_shopping_lists_owner_id", table_name="shopping_lists")
    op.drop_table("shopping_lists")
