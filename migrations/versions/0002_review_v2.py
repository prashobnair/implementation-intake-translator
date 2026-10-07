"""Review workflow v2: accounts, roles, sessions, amendments and the audit chain.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing v0.3 review rows stay valid: they become approved, parentless versions.
    with op.batch_alter_table("review_versions") as batch:
        batch.add_column(sa.Column("parent_version", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("state", sa.String(20), nullable=False, server_default="approved")
        )
        batch.add_column(sa.Column("reason", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now())
        )
    op.create_table(
        "accounts",
        sa.Column("username", sa.String(100), primary_key=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "memberships",
        sa.Column("tenant_id", sa.String(100), primary_key=True),
        sa.Column("username", sa.String(100), primary_key=True),
        sa.Column("role", sa.String(20), nullable=False),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "oidc_identities",
        sa.Column("provider", sa.String(30), primary_key=True),
        sa.Column("subject", sa.String(200), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
    )
    op.create_table(
        "case_amendments",
        sa.Column("tenant_id", sa.String(100), primary_key=True),
        sa.Column("event_id", sa.String(100), primary_key=True),
        sa.Column("seq", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("diff_json", sa.Text(), nullable=False),
        sa.Column("packet_json", sa.Text(), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("ts", sa.String(40), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_audit_tenant_id", "audit_log", ["tenant_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_audit_tenant_id", table_name="audit_log")
    for table in (
        "audit_log",
        "case_amendments",
        "oidc_identities",
        "auth_sessions",
        "memberships",
        "accounts",
    ):
        op.drop_table(table)
    with op.batch_alter_table("review_versions") as batch:
        for column in ("created_at", "reason", "state", "parent_version"):
            batch.drop_column(column)
