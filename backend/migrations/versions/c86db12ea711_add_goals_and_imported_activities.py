"""add current target goal and imported activities

Revision ID: c86db12ea711
Revises: 7bc91e4d2a10
Create Date: 2026-08-12 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c86db12ea711"
down_revision: str | None = "7bc91e4d2a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_profile", sa.Column("current_target_goal", sa.Text(), nullable=True))
    op.create_table(
        "imported_activity",
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("workout_entry_id", sa.Uuid(), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workout_entry_id"],
            ["workout_entry.id"],
            name=op.f("fk_imported_activity_workout_entry_id_workout_entry"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_imported_activity")),
        sa.UniqueConstraint("provider", "source_id", name="uq_imported_activity_provider_source"),
        sa.UniqueConstraint("workout_entry_id", name=op.f("uq_imported_activity_workout_entry_id")),
    )
    for column in ("activity_date", "provider", "start_at", "workout_entry_id"):
        op.create_index(op.f(f"ix_imported_activity_{column}"), "imported_activity", [column])


def downgrade() -> None:
    op.drop_table("imported_activity")
    op.drop_column("user_profile", "current_target_goal")
