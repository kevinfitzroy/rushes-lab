"""Pydantic Settings — env-driven config(12-factor)。"""
from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ─── app ──────────────────────────────────────────────────────────────────
    env: str = "dev"
    log_level: str = "INFO"
    log_format: str = "json"          # "json" | "console"

    # ─── postgres ─────────────────────────────────────────────────────────────
    db_url: PostgresDsn = Field(..., description="postgresql+asyncpg://...")

    # ─── redis(cache + arq broker)────────────────────────────────────────────
    redis_url: RedisDsn = Field(..., description="redis://...")

    # ─── MinIO / S3 ───────────────────────────────────────────────────────────
    minio_endpoint_internal: str = Field(..., description="容器内访问 MinIO 用,e.g. http://poc-pigsty-minio:9000")
    minio_endpoint_public: str = Field(..., description="浏览器访问 MinIO 用(签 presigned URL host),e.g. https://rusheslab.taoxiplan.com")
    minio_access_key: str
    minio_secret_key: str
    minio_default_bucket: str = "incoming"

    # ─── OpenFGA ──────────────────────────────────────────────────────────────
    openfga_api_url: str = Field(..., description="e.g. http://poc-openfga:8080")
    openfga_store_id: str = Field(..., description="启动时通过 list stores + name=material-storage-poc 找;或固化")
    openfga_model_id: str | None = Field(None, description="可选;None = 用 store latest model")

    # ─── 飞书 ────────────────────────────────────────────────────────────────
    feishu_app_id: str
    feishu_app_secret: str
    feishu_bridge_url: str = Field(..., description="bridge service base URL,e.g. http://feishu-bridge:8000")
    feishu_oidc_issuer: str = Field(..., description="MS-FB-004 OIDC issuer,e.g. https://feishu-bridge.example/oidc")

    # ─── presigned URL TTL ────────────────────────────────────────────────────
    presigned_normal_ttl_seconds: int = 900       # 15 min,普通文件
    presigned_sensitive_ttl_seconds: int = 600    # 10 min,敏感文件(配合 OpenFGA grant duration)

    # ─── audit 留存 ───────────────────────────────────────────────────────────
    audit_retention_days: int = 365


# 单例(import 时 lazy 创建)
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
