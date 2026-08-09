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
    # 必填:指派的项目 admin(系统 admin 创建,需要明确指派 sub-admin;
    # 可以是自己 = me.id;UI 默认填创建者)
    admin_user_id: uuid.UUID = Field(..., description="项目管理员的 users.id UUID")


class AdminBrief(BaseModel):
    user_id: str
    name: str


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
    admins: list[AdminBrief] = []
    # 当前 user 在本项目的有效 role 列表(单 user 可有多 role,如 admin+uploader);
    # ['admin'|'uploader'|'downloader'|'viewer'];空 = 仅靠 visibility=public 见
    my_roles: list[str] = []


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
    # 标签 + 盲搜(#151):用户自由标签 + 备注
    user_labels: list[str] = []
    notes: str | None = None


class SearchResultOut(AssetOut):
    """跨 folder 盲搜结果 — AssetOut + 归属信息(前端导航 / 展示用)。"""

    folder_name: str
    project_id: uuid.UUID
    project_name: str


class AssetMetaUpdateIn(BaseModel):
    """打标 / 改标(#151)。

    user_labels / notes 缺省 = 不改该项;显式传空数组 / 空串 = 清空。
    """

    user_labels: list[str] | None = None
    notes: str | None = None


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
    # #129: 加 folder 支持(model + permissions + approval_service 全链路接通)
    target_type: str = Field(..., pattern=r"^(sensitive_folder|asset|project|folder)$")
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
    # 当前 user 对本 folder 的有效权限(派生 can_*)— get_folder 时填充
    my_can_view: bool = False
    my_can_download: bool = False
    my_can_upload: bool = False
    my_can_admin: bool = False


class FolderInviteIn(BaseModel):
    # subject 二选一 — 任选其一传(#154:department 轴写入下线,ADR-0007):
    user_id: uuid.UUID | None = None      # 单人 user(users.id UUID)
    group_id: str | None = None           # 本地用户组(groups.id UUID)
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
    # #136/#137: router 层 enrich(approval row 无这俩列;反查 resolve_target_name)
    # target_name = 人类可读资源名;parent_project_id = folder/asset 时的父项目(导航用)
    target_name: str | None = None
    parent_project_id: uuid.UUID | None = None


# ─── 本地账号密码登录(#149)──────────────────────────────────────────────
class LocalLoginIn(BaseModel):
    """账号密码登录;username 不强制邮箱格式(拼音 / 工号友好)。"""

    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=128)


class ChangePasswordIn(BaseModel):
    """修改密码:old_password 必填;new_password 走密码策略校验。"""

    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=1, max_length=128)
