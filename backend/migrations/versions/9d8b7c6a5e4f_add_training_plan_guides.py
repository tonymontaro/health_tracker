"""add replaceable training plan guides

Revision ID: 9d8b7c6a5e4f
Revises: f4a8c10b2d77
Create Date: 2026-08-18 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9d8b7c6a5e4f"
down_revision: str | None = "f4a8c10b2d77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "training_plan_guide",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "guide_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("raw_csv_text", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["user_profile.id"],
            name=op.f("fk_training_plan_guide_profile_id_user_profile"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_training_plan_guide")),
        sa.UniqueConstraint("profile_id", name=op.f("uq_training_plan_guide_profile_id")),
    )
    op.create_index(
        op.f("ix_training_plan_guide_start_date"),
        "training_plan_guide",
        ["start_date"],
    )
    op.create_index(
        op.f("ix_training_plan_guide_end_date"),
        "training_plan_guide",
        ["end_date"],
    )
    op.alter_column("user_profile", "max_exercises_per_day", server_default="4")
    op.execute(
        "UPDATE user_profile SET max_exercises_per_day = 4 "
        "WHERE max_exercises_per_day = 3"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE user_profile SET max_exercises_per_day = 3 "
        "WHERE max_exercises_per_day = 4"
    )
    op.alter_column("user_profile", "max_exercises_per_day", server_default=None)
    op.drop_table("training_plan_guide")
