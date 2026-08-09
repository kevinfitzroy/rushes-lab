"""#153 应用内通知中心 — 服务层单测。

策略:本机无 docker/容器运行时,不连真 DB / OpenFGA / SMTP;
用 stub db + monkeypatch 覆盖纯逻辑与写入口 fan-out 行为。
容器内全链路 e2e(申请→admin 通知→审批→结果通知)在 tests/test_notifications_e2e.py,PR 标注待 docker 环境。
"""
from __future__ import annotations

import smtplib
import uuid
from types import SimpleNamespace

import pytest

from app.db.tables import ApprovalRequest, Folder, Project, User
from app.services import notifications as ns
from app.settings import Settings


# ─── helpers ──────────────────────────────────────────────────────────────────
def mk_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "env": "test",
        "db_url": "postgresql+asyncpg://u:p@localhost/db",
        "redis_url": "redis://localhost:6379/0",
        "minio_endpoint_internal": "http://minio:9000",
        "minio_endpoint_public": "http://localhost:9000",
        "minio_access_key": "k",
        "minio_secret_key": "s",
        "openfga_api_url": "http://openfga:8080",
        "openfga_store_id": "01TEST",
        "web_app_base_url": "http://localhost/ms-static/web/",
        "session_jwt_secret": "test-secret",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class StubDB:
    """最小 async db 替身:get 查预置对象,execute 返固定行,add/commit 记录。"""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.objects: dict[tuple[object, object], object] = {}
        self.execute_rows: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def get(self, model: object, pk: object) -> object | None:
        return self.objects.get((model, pk))

    async def execute(self, _stmt: object) -> SimpleNamespace:
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(self.execute_rows)))


class StubPermissions:
    def __init__(self, ids: list[str]) -> None:
        self.ids = ids
        self.calls: list[dict[str, str]] = []

    async def list_users_with_relation(self, **kw: str) -> list[str]:
        self.calls.append(kw)
        return self.ids


class StubAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def write(self, **kw: object) -> None:
        self.events.append(kw)


def fake_user(uid: uuid.UUID, *, name: str = "张三", email: str | None = None,
              is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uid, name=name, email=email, is_active=is_active)


def fake_approval(*, uid: uuid.UUID | None = None, status: str = "pending",
                  target_type: str = "sensitive_folder", action: str = "access",
                  duration_seconds: int | None = None, reason: str = "需要素材",
                  approver_user_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uid or uuid.uuid4(),
        target_type=target_type,
        target_id=uuid.uuid4(),
        action=action,
        duration_seconds=duration_seconds,
        reason=reason,
        status=status,
        applicant_user_id=uuid.uuid4(),
        approver_user_id=approver_user_id,
        decision_note=None,
    )

def _async_record(created: list[dict[str, object]]) -> object:
    """返一个 async 记录函数,替代 create_notification(测试内 await 用)。"""

    async def record(db_: object, **kw: object) -> None:
        created.append(kw)

    return record


# ─── SMTP 配置开关 ──────────────────────────────────────────────────────────
def test_smtp_disabled_by_default() -> None:
    assert mk_settings().smtp_enabled is False


def test_smtp_enabled_requires_host_and_from() -> None:
    assert mk_settings(smtp_host="h", smtp_from_email=None).smtp_enabled is False
    assert mk_settings(smtp_host=None, smtp_from_email="f@x.com").smtp_enabled is False
    assert mk_settings(smtp_host="h", smtp_from_email="f@x.com").smtp_enabled is True


# ─── create_notification:落库 + 邮件 ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_create_notification_inserts_row(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ns, "get_settings", lambda: mk_settings())  # smtp 关
    db = StubDB()
    uid = uuid.uuid4()
    await ns.create_notification(db, user_id=uid, kind=ns.KIND_APPROVAL_PENDING, title="t", body="b", link="l")

    assert len(db.added) == 1
    row = db.added[0]
    assert row.user_id == uid and row.kind == "approval_pending"
    assert row.title == "t" and row.body == "b" and row.link == "l"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_create_notification_unknown_kind_skipped() -> None:
    db = StubDB()
    await ns.create_notification(db, user_id=uuid.uuid4(), kind="bogus_kind", title="t")
    assert db.added == []


@pytest.mark.asyncio
async def test_create_notification_emails_when_smtp_on_and_user_has_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = mk_settings(smtp_host="h", smtp_from_email="f@x.com")
    monkeypatch.setattr(ns, "get_settings", lambda: settings)
    sent: list[tuple[str, str, str | None, str | None]] = []

    async def fake_mail(s: Settings, **kw: str | None) -> None:
        sent.append((kw["to_email"], kw["title"], kw["body"], kw["link"]))

    monkeypatch.setattr(ns, "_maybe_send_email", fake_mail)
    db = StubDB()
    uid = uuid.uuid4()
    db.objects[(User, uid)] = (
        fake_user(uid, email="a@b.com"))
    await ns.create_notification(db, user_id=uid, kind=ns.KIND_APPROVAL_PENDING, title="t")

    assert len(sent) == 1 and sent[0][0] == "a@b.com"


@pytest.mark.asyncio
async def test_create_notification_no_email_when_smtp_off_or_user_no_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ns, "get_settings", lambda: mk_settings())
    sent: list[str] = []
    monkeypatch.setattr(ns, "_maybe_send_email",
                        lambda s, **kw: sent.append(kw["to_email"]))  # type: ignore[arg-type]
    db = StubDB()
    uid = uuid.uuid4()
    db.objects[(User, uid)] = (
        fake_user(uid, email=None))
    await ns.create_notification(db, user_id=uid, kind=ns.KIND_APPROVAL_PENDING, title="t")
    assert sent == []


# ─── _smtp_send_sync:纯同步发送逻辑 ─────────────────────────────────────────
def test_smtp_send_sync_tls_with_login(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            calls["ctor"] = (host, port, timeout)

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(self, *a: object) -> bool:
            return False

        def starttls(self) -> None:
            calls["starttls"] = True

        def login(self, u: str, p: str) -> None:
            calls["login"] = (u, p)

        def send_message(self, msg: object) -> None:
            calls["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    settings = mk_settings(smtp_host="h", smtp_from_email="f@x.com",
                           smtp_username="u", smtp_password="p",
                           smtp_use_tls=True, smtp_use_ssl=False)
    ns._smtp_send_sync(settings, "to@x.com", "subject", "body")

    assert calls["ctor"] == ("h", 587, 15)
    assert calls["starttls"] is True
    assert calls["login"] == ("u", "p")
    assert calls["msg"]["To"] == "to@x.com"  # type: ignore[index]
    assert calls["msg"]["From"] == "f@x.com"  # type: ignore[index]


def test_smtp_send_sync_ssl_anonymous(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    class FakeSMTPSSL:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            calls["ctor"] = (host, port, timeout)

        def __enter__(self) -> FakeSMTPSSL:
            return self

        def __exit__(self, *a: object) -> bool:
            return False

        def login(self, u: str, p: str) -> None:  # 不应被调用
            calls["login"] = (u, p)

        def send_message(self, msg: object) -> None:
            calls["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTPSSL)
    settings = mk_settings(smtp_host="h", smtp_from_email="f@x.com",
                           smtp_port=465, smtp_use_tls=False, smtp_use_ssl=True)
    ns._smtp_send_sync(settings, "to@x.com", "s", "b")

    assert calls["ctor"] == ("h", 465, 15)
    assert "login" not in calls  # 未配 username → 匿名发送


# ─── 写入口:审批待办 → admin fan-out ────────────────────────────────────────
@pytest.mark.asyncio
async def test_notify_approval_pending_fans_out_to_active_admins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval = fake_approval()
    admin_a, admin_b = uuid.uuid4(), uuid.uuid4()
    db = StubDB()
    db.objects[(ApprovalRequest,
                approval.id)] = approval
    db.objects[(User,
                approval.applicant_user_id)] = fake_user(approval.applicant_user_id)
    db.execute_rows = [admin_a]  # 仅 admin_a active(模拟 SQL active 过滤)
    perms = StubPermissions([str(admin_a), str(admin_b)])
    audit = StubAudit()

    created: list[dict[str, object]] = []
    monkeypatch.setattr(ns, "create_notification",
                        _async_record(created))  # type: ignore[arg-type]
    monkeypatch.setattr(ns, "get_settings", lambda: mk_settings())

    await ns.notify_approval_pending(approval_id=approval.id, db=db, permissions=perms, audit=audit)

    assert len(created) == 1
    c = created[0]
    assert c["user_id"] == admin_a and c["kind"] == ns.KIND_APPROVAL_PENDING
    assert "新的权限申请" in c["title"]
    assert c["link"] == "http://localhost/ms-static/web/approvals"
    assert perms.calls[0]["relation"] == "can_admin"
    assert len(audit.events) == 1
    assert audit.events[0]["event_type"] == "notification_sent"


@pytest.mark.asyncio
async def test_notify_approval_pending_no_admins_no_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval = fake_approval()
    db = StubDB()
    db.objects[(ApprovalRequest,
                approval.id)] = approval
    db.execute_rows = []
    perms = StubPermissions([])
    audit = StubAudit()
    created: list[object] = []
    monkeypatch.setattr(ns, "create_notification",
                        _async_record(created))  # type: ignore[arg-type]
    monkeypatch.setattr(ns, "get_settings", lambda: mk_settings())

    await ns.notify_approval_pending(approval_id=approval.id, db=db, permissions=perms, audit=audit)
    assert created == [] and audit.events == []


@pytest.mark.asyncio
async def test_notify_approval_pending_missing_approval_noop() -> None:
    db = StubDB()
    audit = StubAudit()
    await ns.notify_approval_pending(
        approval_id=uuid.uuid4(), db=db, permissions=StubPermissions([]), audit=audit,
    )
    assert db.added == [] and audit.events == []


# ─── 写入口:审批结果 → 申请人 ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_notify_approval_decided_approved(monkeypatch: pytest.MonkeyPatch) -> None:
    approval = fake_approval(status="approved", approver_user_id=uuid.uuid4())
    applicant = fake_user(approval.applicant_user_id)
    db = StubDB()
    db.objects[(ApprovalRequest,
                approval.id)] = approval
    db.objects[(User,
                approval.applicant_user_id)] = applicant
    db.objects[(User,
                approval.approver_user_id)] = fake_user(approval.approver_user_id, name="李四")
    audit = StubAudit()

    created: list[dict[str, object]] = []
    monkeypatch.setattr(ns, "create_notification",
                        _async_record(created))  # type: ignore[arg-type]
    monkeypatch.setattr(ns, "get_settings", lambda: mk_settings())

    await ns.notify_approval_decided(approval_id=approval.id, db=db, audit=audit)

    assert len(created) == 1
    c = created[0]
    assert c["user_id"] == applicant.id and c["kind"] == ns.KIND_APPROVAL_DECIDED
    assert "已通过" in c["title"]
    assert "李四" in c["body"]


@pytest.mark.asyncio
async def test_notify_approval_decided_pending_status_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    approval = fake_approval(status="pending")
    db = StubDB()
    db.objects[(ApprovalRequest,
                approval.id)] = approval
    created: list[object] = []
    monkeypatch.setattr(ns, "create_notification",
                        _async_record(created))  # type: ignore[arg-type]
    monkeypatch.setattr(ns, "get_settings", lambda: mk_settings())
    await ns.notify_approval_decided(approval_id=approval.id, db=db, audit=StubAudit())
    assert created == []


@pytest.mark.asyncio
async def test_notify_approval_decided_inactive_applicant_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval = fake_approval(status="approved")
    db = StubDB()
    db.objects[(ApprovalRequest,
                approval.id)] = approval
    db.objects[(User,
                approval.applicant_user_id)] = fake_user(
                    approval.applicant_user_id, is_active=False)
    created: list[object] = []
    monkeypatch.setattr(ns, "create_notification",
                        _async_record(created))  # type: ignore[arg-type]
    monkeypatch.setattr(ns, "get_settings", lambda: mk_settings())
    await ns.notify_approval_decided(approval_id=approval.id, db=db, audit=StubAudit())
    assert created == []


# ─── 写入口:敏感目录邀请 ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_notify_folder_invite(monkeypatch: pytest.MonkeyPatch) -> None:
    folder_id, project_id = uuid.uuid4(), uuid.uuid4()
    inviter = fake_user(uuid.uuid4(), name="王五")
    invitee = fake_user(uuid.uuid4())
    db = StubDB()
    db.objects[(User, invitee.id)] = invitee
    db.objects[(User, inviter.id)] = inviter
    db.objects[(Folder, folder_id)] = (
        SimpleNamespace(id=folder_id, project_id=project_id, name="顾客原片"))
    db.objects[(Project, project_id)] = (
        SimpleNamespace(id=project_id, name="医美项目"))
    audit = StubAudit()

    created: list[dict[str, object]] = []
    monkeypatch.setattr(ns, "create_notification",
                        _async_record(created))  # type: ignore[arg-type]
    monkeypatch.setattr(ns, "get_settings", lambda: mk_settings())

    await ns.notify_folder_invite(
        folder_id=folder_id, invitee_user_id=invitee.id, inviter_user_id=inviter.id,
        duration_seconds=None, db=db, audit=audit,
    )

    assert len(created) == 1
    c = created[0]
    assert c["user_id"] == invitee.id and c["kind"] == ns.KIND_FOLDER_INVITE
    assert "顾客原片" in c["title"] and "永久" in c["body"]
    assert c["link"] == (
        f"http://localhost/ms-static/web/projects/{project_id}/folders/{folder_id}")
    assert audit.events[0]["event_type"] == "notification_sent"


# ─── helpers 纯逻辑 ──────────────────────────────────────────────────────────
def test_web_url_joins_under_basename() -> None:
    settings = mk_settings(web_app_base_url="http://h/ms-static/web/")
    assert ns._web_url(settings, "approvals") == "http://h/ms-static/web/approvals"
    assert ns._web_url(settings, "projects", "p1", "folders", "f1") == (
        "http://h/ms-static/web/projects/p1/folders/f1")


def test_duration_label() -> None:
    assert ns._duration_label(30) == "30 秒"
    assert ns._duration_label(120) == "2 分钟"
    assert ns._duration_label(7200) == "2 小时"
    assert ns._duration_label(2 * 86400) == "2 天"
