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
    organization_id: uuid.UUID
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
