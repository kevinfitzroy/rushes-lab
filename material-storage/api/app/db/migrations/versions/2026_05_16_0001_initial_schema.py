"""initial schema — Phase B-2 first migration

Revision ID: 20260516_0001
Revises:
Create Date: 2026-05-16

6 表:organizations / users / projects / folders / assets / audit_events
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260516_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("feishu_tenant_key", sa.String(64), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("feishu_open_id", sa.String(64), unique=True, nullable=False),
        sa.Column("feishu_union_id", sa.String(64)),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("email", sa.String(255)),
        sa.Column("is_active", sa.Boolean, default=True, nullable=False),
        sa.Column("resigned_at", sa.DateTime(timezone=True)),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_feishu_open_id", "users", ["feishu_open_id"])
    op.create_index("ix_users_feishu_union_id", "users", ["feishu_union_id"])

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("minio_bucket", sa.String(63), nullable=False),
        sa.Column("is_archived", sa.Boolean, default=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "folders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_folder_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("folders.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("minio_prefix", sa.String(1024), nullable=False),
        sa.Column("is_sensitive", sa.Boolean, default=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "minio_prefix", name="uq_folder_project_prefix"),
    )
    op.create_index("ix_folder_project_sensitive", "folders", ["project_id", "is_sensitive"])

    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("folder_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("folders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("minio_bucket", sa.String(63), nullable=False),
        sa.Column("minio_key", sa.String(1024), nullable=False),
        sa.Column("etag", sa.String(128)),
        sa.Column("minio_version_id", sa.String(128)),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("content_type", sa.String(255)),
        sa.Column("media_metadata", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("tags", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("uploader_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("minio_bucket", "minio_key", "minio_version_id",
                            name="uq_asset_minio_object_version"),
    )
    op.create_index("ix_asset_folder_created", "assets", ["folder_id", "created_at"])
    op.create_index("ix_asset_filename", "assets", ["filename"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("actor_open_id_snapshot", sa.String(64)),
        sa.Column("actor_name_snapshot", sa.String(128)),
        sa.Column("actor_email_snapshot", sa.String(255)),
        sa.Column("target_asset_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("assets.id", ondelete="SET NULL")),
        sa.Column("target_project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("target_minio_key", sa.String(1024)),
        sa.Column("dedup_key", sa.String(255), unique=True, nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True)),
        sa.Column("request_ip", sa.String(64)),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("details", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_event_type_time", "audit_events", ["event_type", "event_time"])
    op.create_index("ix_audit_actor_time", "audit_events", ["actor_user_id", "event_time"])
    op.create_index("ix_audit_event_target_asset", "audit_events", ["target_asset_id"])
    op.create_index("ix_audit_event_target_project", "audit_events", ["target_project_id"])
    op.create_index("ix_audit_event_trace_id", "audit_events", ["trace_id"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("assets")
    op.drop_table("folders")
    op.drop_table("projects")
    op.drop_table("users")
    op.drop_table("organizations")
