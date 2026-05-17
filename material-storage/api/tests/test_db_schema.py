"""DB schema smoke test — Phase B-2。

不连真实 DB,只 verify model 定义有效(metadata create / drop OK)。
集成 test 需要起 PG + 跑 migration,留 Phase B-3 CI。
"""
from app.db.tables import Asset, AuditEvent, Base, Folder, Organization, Project, User


def test_all_tables_in_metadata() -> None:
    table_names = {t.name for t in Base.metadata.tables.values()}
    assert table_names == {
        "organizations",
        "users",
        "projects",
        "folders",
        "assets",
        "audit_events",
        "approvals",
    }


def test_asset_unique_constraint() -> None:
    """asset 表必须有 (bucket, key, version) 唯一约束。"""
    constraints = {c.name for c in Asset.__table__.constraints}
    assert "uq_asset_minio_object_version" in constraints


def test_folder_unique_constraint() -> None:
    constraints = {c.name for c in Folder.__table__.constraints}
    assert "uq_folder_project_prefix" in constraints


def test_audit_event_indices() -> None:
    """audit_events 必须有 event_type + time 复合索引(查询性能)。"""
    indices = {idx.name for idx in AuditEvent.__table__.indexes}
    assert "ix_audit_event_type_time" in indices
    assert "ix_audit_actor_time" in indices


def test_user_open_id_unique() -> None:
    """飞书 open_id 是 user 唯一标识。"""
    col = User.__table__.c.feishu_open_id
    assert col.unique is True
    assert col.nullable is False
