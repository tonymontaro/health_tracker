"""version two week plans for manual regeneration

Revision ID: f4a8c10b2d77
Revises: e8f3a1c92d6b
Create Date: 2026-08-17 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a8c10b2d77"
down_revision: str | None = "e8f3a1c92d6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "two_week_plan",
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
    )
    op.drop_constraint(
        op.f("uq_two_week_plan_anchor_date"),
        "two_week_plan",
        type_="unique",
    )
    op.create_unique_constraint(
        op.f("uq_two_week_plan_anchor_date_revision"),
        "two_week_plan",
        ["anchor_date", "revision"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("uq_two_week_plan_anchor_date_revision"),
        "two_week_plan",
        type_="unique",
    )
    op.execute(
        """
        DELETE FROM two_week_plan older
        USING two_week_plan newer
        WHERE older.anchor_date = newer.anchor_date
          AND older.revision < newer.revision
        """
    )
    op.create_unique_constraint(
        op.f("uq_two_week_plan_anchor_date"),
        "two_week_plan",
        ["anchor_date"],
    )
    op.drop_column("two_week_plan", "revision")
