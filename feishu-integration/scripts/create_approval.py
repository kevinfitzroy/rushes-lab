"""端到端审批测试脚本(dev tool,不是生产路径)。

干两件事:
1. `--create-template`:创建一个最简审批模板(textarea「申请理由」+ START + OR/Free 审批节点 + END),
   把生成的 approval_code 打印出来。同样的 form/node 结构跑两次会创建两个不同的模板。
2. 默认行为:用 $TEST_APPROVAL_CODE 创建一个审批实例,申请人/审批人都是 --user,等于"自己审批自己"。

跑这个脚本前提:
- 服务器上 /opt/feishu-poc/.env 已配 FEISHU_APP_ID/SECRET
- 应用已申请 approval:approval 权限并发布
- 在飞书事件订阅页订阅了审批实例相关事件并发布(否则审批人通过/拒绝后 bridge 收不到回调)

跑法(在服务器上):
    cd /opt/feishu-poc
    set -a; . .env; set +a
    .venv/bin/python3 scripts/create_approval.py --user ou_xxxxxxxxxxxx
    .venv/bin/python3 scripts/create_approval.py --create-template
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

FEISHU = "https://open.feishu.cn/open-apis"


def get_token() -> str:
    r = httpx.post(
        f"{FEISHU}/auth/v3/tenant_access_token/internal",
        json={
            "app_id": os.environ["FEISHU_APP_ID"],
            "app_secret": os.environ["FEISHU_APP_SECRET"],
        },
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if data["code"] != 0:
        raise RuntimeError(f"token failed: {data}")
    return data["tenant_access_token"]


def create_template(tok: str) -> str:
    form_widgets = [
        {"id": "reason", "type": "textarea", "name": "@i18n@reason_label", "required": True},
    ]
    payload = {
        "approval_name": "@i18n@approval_name",
        "description": "@i18n@desc_text",
        "viewers": [{"viewer_type": "TENANT"}],
        "form": {"form_content": json.dumps(form_widgets, ensure_ascii=False)},
        "node_list": [
            {"id": "START"},
            {"id": "node_approver", "name": "@i18n@approver_label",
             "node_type": "OR", "approver": [{"type": "Free"}]},
            {"id": "END"},
        ],
        "i18n_resources": [{
            "locale": "zh-CN",
            "is_default": True,
            "texts": [
                {"key": "@i18n@approval_name", "value": "rushes-lab PoC 测试审批"},
                {"key": "@i18n@desc_text", "value": "PoC 端到端测试模板"},
                {"key": "@i18n@reason_label", "value": "申请理由"},
                {"key": "@i18n@approver_label", "value": "审批人"},
            ],
        }],
        "process_manager_ids": [],
    }
    r = httpx.post(
        f"{FEISHU}/approval/v4/approvals?user_id_type=open_id",
        headers={"Authorization": f"Bearer {tok}",
                 "Content-Type": "application/json; charset=utf-8"},
        json=payload, timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data["code"] != 0:
        raise RuntimeError(f"create template failed: {data}")
    return data["data"]["approval_code"]


def create_instance(tok: str, approval_code: str, user_open_id: str, reason: str) -> str:
    form_values = [{"id": "reason", "type": "textarea", "value": reason}]
    payload = {
        "approval_code": approval_code,
        "user_id": user_open_id,
        "open_id": user_open_id,
        "form": json.dumps(form_values, ensure_ascii=False),
        # key 必须与 create_template() 里 node_list 中业务节点的 id 严格一致;
        # 换模板时一并改,否则飞书会返回"approver not found"类错误。
        "node_approver_open_id_list": [
            {"key": "node_approver", "value": [user_open_id]},
        ],
    }
    r = httpx.post(
        f"{FEISHU}/approval/v4/instances",
        headers={"Authorization": f"Bearer {tok}",
                 "Content-Type": "application/json; charset=utf-8"},
        json=payload, timeout=15,
    )
    print(f"POST /instances → HTTP {r.status_code}")
    data = r.json()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    if data.get("code") != 0:
        raise RuntimeError("create instance failed")
    return data["data"]["instance_code"]


def get_instance(tok: str, instance_code: str) -> dict:
    r = httpx.get(
        f"{FEISHU}/approval/v4/instances/{instance_code}?user_id_type=open_id",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    return r.json()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--create-template", action="store_true",
                   help="创建一个新模板,打印 approval_code 后退出")
    p.add_argument("--user", help="申请人/审批人的 open_id (ou_xxxx)")
    p.add_argument("--reason", default="PoC 端到端测试:申请下载 case-lib/clip-019.mp4")
    p.add_argument("--approval-code", default=os.environ.get("TEST_APPROVAL_CODE"))
    args = p.parse_args()

    tok = get_token()
    print(f"token: {tok[:6]}...")

    if args.create_template:
        code = create_template(tok)
        print(f"\napproval_code: {code}")
        return 0

    if not args.user:
        print("错误:--user <open_id> 必填(或加 --create-template)", file=sys.stderr)
        return 2
    if not args.approval_code:
        print("错误:--approval-code 或 TEST_APPROVAL_CODE 环境变量必填", file=sys.stderr)
        return 2

    print(f"approval_code: {args.approval_code}")
    print(f"applicant/approver open_id: {args.user}")
    print(f"reason: {args.reason}\n")

    instance_code = create_instance(tok, args.approval_code, args.user, args.reason)
    print(f"\ninstance_code: {instance_code}")
    print(f"飞书 App 应该收到审批通知。审批后看 journalctl -u feishu-poc -f\n")

    print("== 立即查一次实例状态 ==")
    time.sleep(1)
    print(json.dumps(get_instance(tok, instance_code), ensure_ascii=False, indent=2)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
