"""Preserve v0.2 ledger/review/project tables and add tenant-scoped storage.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing = set(inspector.get_table_names())
    # Never destroy or rewrite a v0.2 packet. Preserve old tables byte-for-byte.
    if "processed_events" not in existing:
        op.create_table(
            "processed_events",
            sa.Column("event_id", sa.Text(), primary_key=True),
            sa.Column("payload_sha256", sa.Text(), nullable=False),
            sa.Column("packet_json", sa.Text(), nullable=False),
        )
    if "review_decisions" not in existing:
        op.create_table(
            "review_decisions",
            sa.Column("event_id", sa.Text(), primary_key=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("decisions_json", sa.Text(), nullable=False),
            sa.Column("approved_packet_json", sa.Text(), nullable=False),
            sa.Column(
                "reviewed_at",
                sa.Text(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
    if "mock_projects" not in existing:
        op.create_table(
            "mock_projects",
            sa.Column("event_id", sa.Text(), primary_key=True),
            sa.Column("project_json", sa.Text(), nullable=False),
        )
    op.create_table(
        "processed_events_v2",
        sa.Column("tenant_id", sa.String(100), primary_key=True),
        sa.Column("source", sa.String(100), primary_key=True),
        sa.Column("event_id", sa.String(100), primary_key=True),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("packet_json", sa.Text(), nullable=False),
    )
    op.create_index("ix_processed_events_tenant", "processed_events_v2", ["tenant_id"])
    op.create_table(
        "review_versions",
        sa.Column("tenant_id", sa.String(100), primary_key=True),
        sa.Column("event_id", sa.String(100), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("decisions_json", sa.Text(), nullable=False),
        sa.Column("packet_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "raw_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("event_id", sa.String(100), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("body_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("auth_mode", sa.String(30), nullable=False),
    )
    op.create_index("ix_raw_events_retention", "raw_events", ["tenant_id", "received_at"])
    op.create_table(
        "machine_keys",
        sa.Column("tenant_id", sa.String(100), primary_key=True),
        sa.Column("prefix", sa.String(32), primary_key=True),
        sa.Column("digest", sa.String(64), nullable=False),
    )
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")


def downgrade() -> None:
    op.drop_table("machine_keys")
    op.drop_index("ix_raw_events_retention", table_name="raw_events")
    op.drop_table("raw_events")
    op.drop_table("review_versions")
    op.drop_index("ix_processed_events_tenant", table_name="processed_events_v2")
    op.drop_table("processed_events_v2")
    # Never drop the legacy tables on downgrade: they may hold original packets.
