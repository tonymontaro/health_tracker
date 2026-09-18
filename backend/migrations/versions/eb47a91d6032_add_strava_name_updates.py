"""Preserve Strava name updates and manually recorded treadmill incline."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "eb47a91d6032"
down_revision: str | None = "b728ed041c93"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "strava_activity",
        sa.Column(
            "name_update_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("strava_activity", "name_update_json", server_default=None)
    op.add_column(
        "strava_activity", sa.Column("treadmill_incline_percent", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("strava_activity", "treadmill_incline_percent")
    op.drop_column("strava_activity", "name_update_json")
