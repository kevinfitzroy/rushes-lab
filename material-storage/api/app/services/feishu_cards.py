"""飞书 interactive 卡片 builder — 统一模板。

卡片 schema 用 v1.0(`{config, header, elements}`),兼容性最好。
v2.0 schema(`{schema:"2.0", body:{elements:[]}}`)迁移成本暂不引入。

action button 的 `value` 字段在点击时通过 card.action.trigger 事件回传,
约定 schema:
    {"intent": "<approval_decision|share_open|invite_open|...>", ...rest}

调用方:
    from app.services.feishu_cards import build_approval_card
    card = build_approval_card(applicant_name="张三", target_label="某 folder",
                               action_label="临时下载 1h", reason="...",
                               approval_id="<uuid>", web_url="...")
    await feishu.send_im_card(receive_id=admin_open_id, card=card)
"""
from __future__ import annotations

from typing import Any, Literal

CardTemplate = Literal["blue", "green", "orange", "red", "grey", "turquoise", "purple"]


# ─── 通用元素 builder ─────────────────────────────────────────────────────────
def _header(title: str, *, template: CardTemplate = "blue") -> dict[str, Any]:
    return {
        "title": {"tag": "plain_text", "content": title},
        "template": template,
    }


def _markdown(content: str) -> dict[str, Any]:
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}


def _divider() -> dict[str, Any]:
    return {"tag": "hr"}


def _note(text: str) -> dict[str, Any]:
    return {"tag": "note", "elements": [{"tag": "plain_text", "content": text}]}


def _button(
    text: str,
    *,
    button_type: Literal["default", "primary", "danger"] = "default",
    value: dict[str, Any] | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    """callback button(value=)或 link button(url=)二选一。"""
    btn: dict[str, Any] = {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": button_type,
    }
    if value is not None:
        btn["value"] = value
    if url is not None:
        btn["url"] = url
    return btn


def _actions(*buttons: dict[str, Any]) -> dict[str, Any]:
    return {"tag": "action", "actions": list(buttons)}


def _base(*, title: str, template: CardTemplate, elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": _header(title, template=template),
        "elements": elements,
    }


# ─── 1) 权限审批卡片(approve / reject 按钮回调)──────────────────────────────
def build_approval_card(
    *,
    applicant_name: str,
    target_label: str,
    action_label: str,
    reason: str,
    approval_id: str,
    web_url: str | None = None,
) -> dict[str, Any]:
    """approval pending → 推给 admin 决策。

    按钮 value:
      {"intent": "approval_decision", "approval_id": "<uuid>", "decision": "approve|reject"}
    """
    elements: list[dict[str, Any]] = [
        _markdown(
            f"**申请人**:{applicant_name}\n"
            f"**目标**:{target_label}\n"
            f"**类型**:{action_label}\n"
        ),
        _divider(),
        _markdown(f"**申请理由**\n{_quote(reason)}"),
        _actions(
            _button(
                "通过",
                button_type="primary",
                value={"intent": "approval_decision", "approval_id": approval_id, "decision": "approve"},
            ),
            _button(
                "拒绝",
                button_type="danger",
                value={"intent": "approval_decision", "approval_id": approval_id, "decision": "reject"},
            ),
            *([_button("详情", url=web_url)] if web_url else []),
        ),
        _note(f"审批 ID:{approval_id}"),
    ]
    return _base(title="🔔 权限审批申请", template="blue", elements=elements)


def build_approval_decided_card(
    *,
    applicant_name: str,
    target_label: str,
    action_label: str,
    decision: Literal["approve", "reject"],
    decided_by_name: str,
    decision_note: str | None,
    approval_id: str,
) -> dict[str, Any]:
    """update 卡片:audit 已处理(同 message_id 调 update_im_card)。

    或推给申请者:你的申请 已通过/已拒绝。
    """
    if decision == "approve":
        title = "✅ 审批已通过"
        template: CardTemplate = "green"
        verb = "已通过"
    else:
        title = "❌ 审批已拒绝"
        template = "red"
        verb = "已拒绝"

    elements: list[dict[str, Any]] = [
        _markdown(
            f"**申请人**:{applicant_name}\n"
            f"**目标**:{target_label}\n"
            f"**类型**:{action_label}\n"
            f"**决策**:{verb}(by {decided_by_name})"
        ),
    ]
    if decision_note:
        elements.append(_divider())
        elements.append(_markdown(f"**决策说明**\n{_quote(decision_note)}"))
    elements.append(_note(f"审批 ID:{approval_id}"))

    return _base(title=title, template=template, elements=elements)


# ─── 2) 资源分享卡片(打开链接按钮)─────────────────────────────────────────
def build_share_card(
    *,
    sharer_name: str,
    resource_label: str,
    resource_type: Literal["asset", "folder"],
    open_url: str,
    expires_label: str,
    message: str | None = None,
) -> dict[str, Any]:
    """分享给接收人 — 卡片含资源信息 + 打开按钮(走 share/{token} 短链)。"""
    icon = "📄" if resource_type == "asset" else "📁"
    elements: list[dict[str, Any]] = [
        _markdown(
            f"**{sharer_name}** 分享了一份{('文件' if resource_type == 'asset' else '文件夹')}给你:\n"
            f"{icon} **{resource_label}**\n"
        ),
    ]
    if message:
        elements.append(_divider())
        elements.append(_markdown(f"**留言**\n{_quote(message)}"))
    elements.append(_divider())
    elements.append(_actions(_button("打开查看", button_type="primary", url=open_url)))
    elements.append(_note(f"链接有效期:{expires_label}"))
    return _base(title="📨 资源分享", template="turquoise", elements=elements)


# ─── 3) 邀请卡片(打开项目/folder 按钮)────────────────────────────────────
def build_invite_card(
    *,
    inviter_name: str,
    target_label: str,
    target_type: Literal["project", "sensitive_folder"],
    role_label: str,
    open_url: str,
    duration_label: str | None = None,
) -> dict[str, Any]:
    """admin 邀请 user 加入 project / sensitive_folder。

    duration_label=None → 永久邀请;不为 None → 临时邀请(显示倒计时友好文案)。
    """
    icon = "📁" if target_type == "sensitive_folder" else "📦"
    type_text = "敏感文件夹" if target_type == "sensitive_folder" else "项目"
    elements: list[dict[str, Any]] = [
        _markdown(
            f"**{inviter_name}** 邀请你加入{type_text}:\n"
            f"{icon} **{target_label}**\n"
            f"**角色**:{role_label}"
            + (f"\n**有效期**:{duration_label}" if duration_label else "")
        ),
        _divider(),
        _actions(_button("打开查看", button_type="primary", url=open_url)),
    ]
    return _base(title="🎉 邀请通知", template="purple", elements=elements)


# ─── helpers ──────────────────────────────────────────────────────────────────
def _quote(text: str, *, max_len: int = 500) -> str:
    """飞书 lark_md quote 块(每行前 `> `),长文本自动截断。"""
    body = text.strip()
    if len(body) > max_len:
        body = body[: max_len - 1] + "…"
    return "\n".join(f"> {line}" if line else ">" for line in body.splitlines())
