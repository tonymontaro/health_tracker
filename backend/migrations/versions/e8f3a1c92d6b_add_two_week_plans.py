"""add rolling two week plans

Revision ID: e8f3a1c92d6b
Revises: a19d3e84c7f2
Create Date: 2026-08-16 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8f3a1c92d6b"
down_revision: str | None = "a19d3e84c7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "two_week_plan",
        sa.Column("anchor_date", sa.Date(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("previous_plan_id", sa.Uuid(), nullable=True),
        sa.Column("profile_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("planner_version", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column(
            "context_snapshot_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("plan_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "validation_result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["previous_plan_id"],
            ["two_week_plan.id"],
            name=op.f("fk_two_week_plan_previous_plan_id_two_week_plan"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["profile_snapshot_id"],
            ["profile_snapshot.id"],
            name=op.f("fk_two_week_plan_profile_snapshot_id_profile_snapshot"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_two_week_plan")),
        sa.UniqueConstraint("anchor_date", name=op.f("uq_two_week_plan_anchor_date")),
    )
    op.create_index(
        op.f("ix_two_week_plan_anchor_date"), "two_week_plan", ["anchor_date"]
    )
    op.create_index(
        op.f("ix_two_week_plan_window_start"), "two_week_plan", ["window_start"]
    )
    op.create_index(op.f("ix_two_week_plan_window_end"), "two_week_plan", ["window_end"])
    op.create_index(
        op.f("ix_two_week_plan_previous_plan_id"),
        "two_week_plan",
        ["previous_plan_id"],
    )


def downgrade() -> None:
    op.drop_table("two_week_plan")
