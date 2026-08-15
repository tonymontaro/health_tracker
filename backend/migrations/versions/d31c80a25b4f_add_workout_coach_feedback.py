"""add persisted workout coach feedback

Revision ID: d31c80a25b4f
Revises: c86db12ea711
Create Date: 2026-08-12 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d31c80a25b4f"
down_revision: str | None = "c86db12ea711"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workout_coach_feedback",
        sa.Column("feedback_date", sa.Date(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("context_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workout_coach_feedback")),
        sa.UniqueConstraint("feedback_date", name=op.f("uq_workout_coach_feedback_feedback_date")),
    )
    op.create_index(
        op.f("ix_workout_coach_feedback_feedback_date"),
        "workout_coach_feedback",
        ["feedback_date"],
    )


def downgrade() -> None:
    op.drop_table("workout_coach_feedback")
