"""Replace inventory with stable calendar meal weeks.

Revision ID: b728ed041c93
Revises: 9d8b7c6a5e4f
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b728ed041c93"
down_revision: str | None = "9d8b7c6a5e4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weekly_meal_plan",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("plan_json", postgresql.JSONB(), nullable=False),
        sa.Column("context_snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column("validation_result_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weekly_meal_plan")),
    )
    op.create_index(
        "ix_weekly_meal_plan_week_start", "weekly_meal_plan", ["week_start"], unique=True
    )
    # Retain old stock and purchase data only as an offline archive for reversible migration.
    # These tables have no application model, endpoint, job, or provider access.
    op.rename_table("inventory_item", "retired_inventory_item")
    op.rename_table("shopping_plan", "retired_shopping_plan")


def downgrade() -> None:
    op.rename_table("retired_shopping_plan", "shopping_plan")
    op.rename_table("retired_inventory_item", "inventory_item")
    op.drop_table("weekly_meal_plan")
