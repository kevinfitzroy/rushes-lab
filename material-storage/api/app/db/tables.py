"""SQLAlchemy 2.x models — Phase B-1 skeleton。

Phase B-2 加完整 schema(参 audit-schema PR #30 修订版 + business entities)。
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# TODO Phase B-1/B-2:
#   User, Organization, Project, Folder, Asset, Approval, Audit, AccessLog, ...
