"""add Strava integration and daily workout logs

Revision ID: 7bc91e4d2a10
Revises: 2adc3fa0e305
Create Date: 2026-08-09 20:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7bc91e4d2a10"
down_revision: str | None = "2adc3fa0e305"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_workout_log",
        sa.Column("log_date", sa.Date(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column(
            "extraction_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "previous_entries_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_workout_log")),
        sa.UniqueConstraint("log_date", name=op.f("uq_daily_workout_log_log_date")),
    )
    op.create_index(
        op.f("ix_daily_workout_log_log_date"),
        "daily_workout_log",
        ["log_date"],
        unique=False,
    )
    op.add_column("workout_entry", sa.Column("workout_log_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_workout_entry_workout_log_id"),
        "workout_entry",
        ["workout_log_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_workout_entry_workout_log_id_daily_workout_log"),
        "workout_entry",
        "daily_workout_log",
        ["workout_log_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "strava_oauth_state",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["user_account.id"],
            name=op.f("fk_strava_oauth_state_account_id_user_account"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strava_oauth_state")),
    )
    op.create_index(
        op.f("ix_strava_oauth_state_account_id"),
        "strava_oauth_state",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_strava_oauth_state_expires_at"),
        "strava_oauth_state",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_strava_oauth_state_state_hash"),
        "strava_oauth_state",
        ["state_hash"],
        unique=True,
    )

    op.create_table(
        "strava_connection",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("athlete_id", sa.BigInteger(), nullable=False),
        sa.Column("athlete_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scopes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["user_account.id"],
            name=op.f("fk_strava_connection_account_id_user_account"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strava_connection")),
        sa.UniqueConstraint("account_id", name=op.f("uq_strava_connection_account_id")),
    )
    op.create_index(
        op.f("ix_strava_connection_athlete_id"),
        "strava_connection",
        ["athlete_id"],
        unique=True,
    )

    op.create_table(
        "strava_activity",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("strava_activity_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("sport_type", sa.String(length=80), nullable=False),
        sa.Column("activity_type", sa.String(length=80), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=False),
        sa.Column("moving_time_seconds", sa.Integer(), nullable=False),
        sa.Column("elapsed_time_seconds", sa.Integer(), nullable=False),
        sa.Column("elevation_gain_m", sa.Float(), nullable=False),
        sa.Column("average_heartrate", sa.Float(), nullable=True),
        sa.Column("max_heartrate", sa.Float(), nullable=True),
        sa.Column("average_watts", sa.Float(), nullable=True),
        sa.Column("device_name", sa.String(length=160), nullable=True),
        sa.Column("trainer", sa.Boolean(), nullable=False),
        sa.Column("commute", sa.Boolean(), nullable=False),
        sa.Column("manual", sa.Boolean(), nullable=False),
        sa.Column("private", sa.Boolean(), nullable=False),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["strava_connection.id"],
            name=op.f("fk_strava_activity_connection_id_strava_connection"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strava_activity")),
        sa.UniqueConstraint(
            "connection_id",
            "strava_activity_id",
            name=op.f("uq_strava_activity_connection_id"),
        ),
    )
    for column in ("activity_date", "connection_id", "start_at", "strava_activity_id"):
        op.create_index(
            op.f(f"ix_strava_activity_{column}"),
            "strava_activity",
            [column],
            unique=False,
        )

    op.create_table(
        "strava_activity_match",
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("workout_entry_id", sa.Uuid(), nullable=False),
        sa.Column("match_kind", sa.String(length=40), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column(
            "previous_entry_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["strava_activity.id"],
            name=op.f("fk_strava_activity_match_activity_id_strava_activity"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workout_entry_id"],
            ["workout_entry.id"],
            name=op.f("fk_strava_activity_match_workout_entry_id_workout_entry"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strava_activity_match")),
        sa.UniqueConstraint(
            "activity_id",
            "workout_entry_id",
            name=op.f("uq_strava_activity_match_activity_id"),
        ),
        sa.UniqueConstraint(
            "workout_entry_id",
            name=op.f("uq_strava_activity_match_workout_entry_id"),
        ),
    )
    op.create_index(
        op.f("ix_strava_activity_match_activity_id"),
        "strava_activity_match",
        ["activity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_strava_activity_match_workout_entry_id"),
        "strava_activity_match",
        ["workout_entry_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_strava_activity_match_workout_entry_id"),
        table_name="strava_activity_match",
    )
    op.drop_index(
        op.f("ix_strava_activity_match_activity_id"),
        table_name="strava_activity_match",
    )
    op.drop_table("strava_activity_match")
    for column in ("strava_activity_id", "start_at", "connection_id", "activity_date"):
        op.drop_index(op.f(f"ix_strava_activity_{column}"), table_name="strava_activity")
    op.drop_table("strava_activity")
    op.drop_index(op.f("ix_strava_connection_athlete_id"), table_name="strava_connection")
    op.drop_table("strava_connection")
    op.drop_index(op.f("ix_strava_oauth_state_state_hash"), table_name="strava_oauth_state")
    op.drop_index(op.f("ix_strava_oauth_state_expires_at"), table_name="strava_oauth_state")
    op.drop_index(op.f("ix_strava_oauth_state_account_id"), table_name="strava_oauth_state")
    op.drop_table("strava_oauth_state")
    op.drop_constraint(
        op.f("fk_workout_entry_workout_log_id_daily_workout_log"),
        "workout_entry",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_workout_entry_workout_log_id"), table_name="workout_entry")
    op.drop_column("workout_entry", "workout_log_id")
    op.drop_index(op.f("ix_daily_workout_log_log_date"), table_name="daily_workout_log")
    op.drop_table("daily_workout_log")
