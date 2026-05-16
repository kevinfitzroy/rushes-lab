"""SQLAlchemy 2.x ORM models — Phase B-2 first batch。

设计要点:
- UUID PK(uuid7 时间排序);created_at / updated_at server-side default
- audit_events 是中心:所有 event 同表 + event_type 区分(简化第一版);
  Phase B-2 后续按事件量评估是否拆 sub-table
- 用户 snapshot 列(open_id / name / email)冗余存,user 软删/inactive 后审计仍可读
  (ADR-0005 §11.2 Gap 10 / PR #30 修订版)
- folder.is_sensitive 标记敏感目录;OpenFGA tuple 用 sensitive_folder type 区分
  (model layer 用 type 级隔离,数据层用 boolean 简化 schema)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """所有 ORM 模型基类。"""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    feishu_tenant_key: Mapped[str | None] = mapped_column(String(64), unique=True)

    projects: Mapped[list["Project"]] = relationship(back_populates="organization")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    feishu_open_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    feishu_union_id: Mapped[str | None] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    resigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None]
    minio_bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    # 元数据可见性(项目列表过滤):
    #   public  — org member 都看到 metadata,可申请加入
    #   private — 只 project member 看到(default)
    #   stealth — 完全隐藏,只 admin 主动邀请(connection 知 code 输入申请)
    visibility: Mapped[str] = mapped_column(String(16), default="private", nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="projects")
    folders: Mapped[list["Folder"]] = relationship(back_populates="project")


class Folder(Base, TimestampMixin):
    __tablename__ = "folders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    parent_folder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("folders.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    minio_prefix: Mapped[str] = mapped_column(String(1024), nullable=False)
    # Deprecated(Phase B-2 next iter):OpenFGA model 不再区分 sensitive/普通 folder type;
    # 字段保留为 future flexibility(可作业务标签),但不驱动权限。可下个 migration drop。
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    project: Mapped[Project] = relationship(back_populates="folders")
    assets: Mapped[list["Asset"]] = relationship(back_populates="folder")

    __table_args__ = (
        UniqueConstraint("project_id", "minio_prefix", name="uq_folder_project_prefix"),
        Index("ix_folder_project_sensitive", "project_id", "is_sensitive"),
    )


class Asset(Base, TimestampMixin):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    folder_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("folders.id", ondelete="RESTRICT"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    minio_bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    minio_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    etag: Mapped[str | None] = mapped_column(String(128))
    minio_version_id: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255))
    media_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    tags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    uploader_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    folder: Mapped[Folder] = relationship(back_populates="assets")

    __table_args__ = (
        UniqueConstraint("minio_bucket", "minio_key", "minio_version_id",
                         name="uq_asset_minio_object_version"),
        Index("ix_asset_folder_created", "folder_id", "created_at"),
        Index("ix_asset_filename", "filename"),
    )


class ApprovalRequest(Base, TimestampMixin):
    """审批申请 — iter6。

    用户对 sensitive_folder / asset 发起下载/访问申请;
    admin 批准 → 写 OpenFGA grant tuple(grant_explicit_download /
    invite_to_sensitive_folder),并把 tuple 引用存在 granted_tuple_ref(JSONB),
    撤销时直接定位删除。
    """
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    applicant_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # 申请目标:('sensitive_folder' | 'asset' | 'project'),配合 target_id 定位
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)

    # 申请的动作:'download'(临时下载)| 'access'(永久邀请 sensitive_folder)
    action: Mapped[str] = mapped_column(String(32), nullable=False)

    duration_seconds: Mapped[int | None]   # None = 永久(action=access 时)
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)

    # pending / approved / rejected / revoked / expired
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)

    # 飞书审批集成(iter7):每个申请对应飞书审批一个 instance
    feishu_instance_code: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)

    # 决策
    approver_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(2000))

    # OpenFGA 写回的 tuple 引用(撤销/审计用)
    # 形如 {"user":"user:X","relation":"explicit_downloader","object":"asset:Y","permanent":false}
    granted_tuple_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_approval_target", "target_type", "target_id"),
        Index("ix_approval_status_created", "status", "created_at"),
    )


class AuditEvent(Base):
    """Audit 中心:所有业务事件落库;ADR-0005 §11.2 Gap 10。"""
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # event_type 枚举(string,Phase B-2 不引入 enum):
    #   upload / download / proxy_download / signed_url_issued / signed_url_revoked
    #   approval_submitted / approval_state_changed
    #   admin_session_login / admin_session_logout / session_revoked_due_to_resign
    #   sidecar_task_started / sidecar_task_succeeded / sidecar_task_failed
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # actor snapshot(冗余,user 删后仍可读)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor_open_id_snapshot: Mapped[str | None] = mapped_column(String(64))
    actor_name_snapshot: Mapped[str | None] = mapped_column(String(128))
    actor_email_snapshot: Mapped[str | None] = mapped_column(String(255))

    target_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), index=True
    )
    target_project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    target_minio_key: Mapped[str | None] = mapped_column(String(1024))

    # 跨系统幂等;格式 <source>:<source_event_id>[:<status>]
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(index=True)

    request_ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))

    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_event_type_time", "event_type", "event_time"),
        Index("ix_audit_actor_time", "actor_user_id", "event_time"),
    )
