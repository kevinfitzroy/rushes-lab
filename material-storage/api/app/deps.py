"""Dependency Injection — db / openfga / feishu / s3 client。

Phase B-1 stub,Phase B-2 实际 wiring。
"""
from app.settings import Settings, get_settings


async def get_db():  # type: ignore[no-untyped-def]
    """async session, yield from app.state.db_pool."""
    # TODO Phase B-1
    yield None


async def get_openfga():  # type: ignore[no-untyped-def]
    """openfga_sdk OpenFgaClient,from app.state.openfga."""
    yield None


async def get_s3_client():  # type: ignore[no-untyped-def]
    """boto3 / aioboto3 client(注意 P-10 双 client:internal / signer)."""
    yield None


def settings_dep() -> Settings:
    return get_settings()
