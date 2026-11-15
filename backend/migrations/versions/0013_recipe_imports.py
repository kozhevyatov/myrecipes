"""Connected recipe sources and durable import jobs.

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

MYSQL = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


def upgrade() -> None:
    op.create_table(
        "import_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("definition_json", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("sample_json", sa.Text(), nullable=False),
        **MYSQL,
    )
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("import_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("parameters_json", sa.Text().with_variant(mysql.LONGTEXT(), "mysql", "mariadb"), nullable=False),
        sa.Column("report_json", sa.Text().with_variant(mysql.LONGTEXT(), "mysql", "mariadb"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("active_slot", sa.String(16), nullable=True, unique=True),
        sa.Column("owner_id", sa.String(64), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        **MYSQL,
    )
    op.create_index("ix_import_jobs_source_id", "import_jobs", ["source_id"])
    op.create_index("ix_import_jobs_author_id", "import_jobs", ["author_id"])
    op.create_index("ix_import_jobs_status", "import_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("import_jobs")
    op.drop_table("import_sources")
