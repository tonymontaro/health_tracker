"""expand inventory items

Revision ID: a19d3e84c7f2
Revises: d31c80a25b4f
Create Date: 2026-08-15 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a19d3e84c7f2"
down_revision: str | None = "d31c80a25b4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("inventory_item", "food_item_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("inventory_item", sa.Column("custom_name", sa.String(length=160)))
    op.add_column(
        "inventory_item",
        sa.Column(
            "item_type",
            sa.String(length=40),
            nullable=False,
            server_default="ingredient",
        ),
    )
    op.add_column("inventory_item", sa.Column("notes", sa.Text()))
    op.add_column(
        "inventory_item",
        sa.Column(
            "source",
            sa.String(length=40),
            nullable=False,
            server_default="shopping",
        ),
    )
    op.create_check_constraint(
        op.f("ck_inventory_item_identity"),
        "inventory_item",
        "food_item_id IS NOT NULL OR (custom_name IS NOT NULL AND btrim(custom_name) <> '')",
    )
    op.alter_column("inventory_item", "item_type", server_default=None)
    op.alter_column("inventory_item", "source", server_default=None)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_inventory_item_identity"), "inventory_item", type_="check")
    op.execute("DELETE FROM inventory_item WHERE food_item_id IS NULL")
    op.drop_column("inventory_item", "source")
    op.drop_column("inventory_item", "notes")
    op.drop_column("inventory_item", "item_type")
    op.drop_column("inventory_item", "custom_name")
    op.alter_column("inventory_item", "food_item_id", existing_type=sa.Uuid(), nullable=False)
