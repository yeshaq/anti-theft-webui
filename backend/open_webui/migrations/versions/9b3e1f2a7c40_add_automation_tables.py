"""Add automation tables

Revision ID: 9b3e1f2a7c40
Revises: 3781e22d8b01
Create Date: 2026-10-29 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "9b3e1f2a7c40"
down_revision = "3781e22d8b01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "automation",
        sa.Column("id", sa.Text(), nullable=False, primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("rrule", sa.Text(), nullable=False),
        sa.Column("dtstart", sa.BigInteger(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.BigInteger(), nullable=True),
        sa.Column("last_run_at", sa.BigInteger(), nullable=True),
        sa.Column("run_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_automation_user_id", "automation", ["user_id"])
    op.create_index(
        "ix_automation_enabled_next_run_at", "automation", ["enabled", "next_run_at"]
    )

    op.create_table(
        "automation_run",
        sa.Column("id", sa.Text(), nullable=False, primary_key=True),
        sa.Column("automation_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("chat_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("started_at", sa.BigInteger(), nullable=False),
        sa.Column("finished_at", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_automation_run_automation_id_started_at",
        "automation_run",
        ["automation_id", "started_at"],
    )


def downgrade():
    op.drop_index("ix_automation_run_automation_id_started_at", "automation_run")
    op.drop_table("automation_run")
    op.drop_index("ix_automation_enabled_next_run_at", "automation")
    op.drop_index("ix_automation_user_id", "automation")
    op.drop_table("automation")
