"""Pydantic API I/O models — Phase B-2 first batch。"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ─── projects ─────────────────────────────────────────────────────────────────
class ProjectCreateIn(BaseModel):
    code: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    # 留空 = 用 user.organization_id 或 settings.default_organization_id
    organization_id: uuid.UUID | None = None
    minio_bucket: str = Field(..., max_length=63)


class ProjectOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    organization_id: uuid.UUID
    minio_bucket: str
    visibility: str       # public / private / stealth
    is_archived: bool
    created_at: datetime


# ─── assets ───────────────────────────────────────────────────────────────────
class AssetOut(ORMModel):
    id: uuid.UUID
    folder_id: uuid.UUID
    filename: str
    minio_bucket: str
    minio_key: str
    etag: str | None
    minio_version_id: str | None
    size_bytes: int
    content_type: str | None
    created_at: datetime
    # B-4:worker 生成的缩略图 / 标签等 metadata;前端按需读
    tags: dict = {}


# ─── upload presigned ─────────────────────────────────────────────────────────
class UploadUrlRequest(BaseModel):
    folder_id: uuid.UUID
    filename: str = Field(..., min_length=1, max_length=512)
    content_type: str = "application/octet-stream"
    size_bytes: int = Field(..., ge=0)


class UploadMultipartCreateOut(BaseModel):
    upload_id: str
    key: str
    bucket: str


class UploadPartUrlOut(BaseModel):
    url: str
    expires_in: int


class UploadCompleteIn(BaseModel):
    upload_id: str
    bucket: str
    key: str
    parts: list[dict[str, int | str]]


# ─── download link ────────────────────────────────────────────────────────────
class DownloadLinkOut(BaseModel):
    url: str
    expires_in: int
    is_sensitive: bool


# ─── approvals(iter6)────────────────────────────────────────────────────────
class ApprovalCreateIn(BaseModel):
    target_type: str = Field(..., pattern=r"^(sensitive_folder|asset|project)$")
    target_id: uuid.UUID
    action: str = Field(..., pattern=r"^(download|access)$",
                        description="download=临时下载(grant_explicit_download);"
                                    "access=邀请进 sensitive_folder")
    duration_seconds: int | None = Field(None, ge=60, le=365 * 24 * 3600,
                                         description="None=永久(仅 action=access 时)")
    reason: str = Field(..., min_length=4, max_length=2000)


class ApprovalDecisionIn(BaseModel):
    decision_note: str | None = Field(None, max_length=2000)


# ─── folders(iter7)──────────────────────────────────────────────────────────
class FolderCreateIn(BaseModel):
    project_id: uuid.UUID
    parent_folder_id: uuid.UUID | None = None
    name: str = Field(..., min_length=1, max_length=255)
    is_sensitive: bool = False
    minio_prefix: str | None = Field(None, max_length=1024,
                                      description="未给则自动 = '<parent_prefix>/<name>/'")


class FolderOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    parent_folder_id: uuid.UUID | None
    name: str
    minio_prefix: str
    is_sensitive: bool
    created_at: datetime


class FolderInviteIn(BaseModel):
    # subject 三选一(飞书 ID)— 任选其一传:
    user_open_id: str | None = None       # 单人 user (飞书 open_id)
    group_id: str | None = None           # 飞书用户组
    department_id: str | None = None      # 飞书部门(含子部门 via OpenFGA 自递归)
    # 邀请等级(v4 新增,旧调用方默认 viewer)
    level: str = Field("viewer", pattern=r"^(viewer|downloader)$")
    duration_seconds: int | None = Field(None, ge=60, le=365 * 24 * 3600,
                                         description="None=永久邀请;int=时间限定")


class ApprovalOut(ORMModel):
    id: uuid.UUID
    applicant_user_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    action: str
    duration_seconds: int | None
    reason: str
    status: str
    feishu_instance_code: str | None
    approver_user_id: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime
