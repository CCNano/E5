#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scheduled Microsoft Graph Task Runner

通过 Azure AD 应用注册（OAuth2 client credentials flow）获取 Microsoft Graph
token，从 config.json 指定的任务类型中随机选择并调用仅产生"自产内容"的
Graph API（Mail 发送/草稿、Calendar、OneDrive、Contacts）。

隐私安全设计（适用于公开仓库）:
    - 不读取、转发、修改任何已有邮件/文件等真实用户数据
    - 仅写自建内容（随机主题/正文/文件/联系人），OneDrive 操作限定在 /daily-sync/ 目录
    - 日志统一脱敏，UPN 一律替换为 userN，不输出任何身份信息

所需 application 权限（管理员同意）:
    Mail.Send, Mail.ReadWrite, Calendars.ReadWrite,
    Files.ReadWrite.All, Contacts.ReadWrite

环境变量（均通过 GitHub Secrets 注入）:
    TENANT_ID      Azure AD 租户 ID
    CLIENT_ID      Azure AD 应用 (客户端) ID
    CLIENT_SECRET  应用密钥
    TARGET_USERS   目标用户 UPN 列表，逗号分隔
"""

import json
import os
import random
import string
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

GRAPH = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

TIMEOUT = 30
MAX_RETRY = 3


# ---------------------------------------------------------------- logging ---

def make_redactor(users):
    mapping = {u: f"user{i}" for i, u in enumerate(users)}

    def redact(msg: str) -> str:
        for raw, alias in mapping.items():
            msg = msg.replace(raw, alias)
        return msg

    return redact


def _identity(m: str) -> str:
    return m


REDACT = _identity


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z] {REDACT(msg)}", flush=True)


# ------------------------------------------------------------------- auth ---

def get_token() -> str:
    """OAuth2 client credentials flow，scope 为 Graph .default（application 权限）。"""
    resp = requests.post(
        TOKEN_URL.format(tenant=os.environ["TENANT_ID"]),
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["CLIENT_ID"],
            "client_secret": os.environ["CLIENT_SECRET"],
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def call_api(token: str, method: str, path: str, **kwargs) -> requests.Response:
    """带重试的 Graph API 调用（日志自动脱敏）。"""
    url = path if path.startswith("http") else GRAPH + path
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    for attempt in range(1, MAX_RETRY + 1):
        try:
            resp = requests.request(method, url, headers=headers,
                                    timeout=TIMEOUT, **kwargs)
            if resp.status_code < 400:
                log(f"OK  {method} {path} -> {resp.status_code}")
                return resp
            log(f"ERR {method} {path} -> {resp.status_code}")
        except requests.RequestException as exc:
            log(f"EXC {method} {path} attempt {attempt}: {type(exc).__name__}")
        if attempt < MAX_RETRY:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"API failed after {MAX_RETRY} retries: {method} {path}")


# ------------------------------------------------------- random utilities ---

def rand_hex(n: int = 8) -> str:
    return "".join(random.choices(string.hexdigits.lower()[:16], k=n))


def rand_word() -> str:
    return "".join(random.choices(string.ascii_lowercase, k=random.randint(4, 10)))


def rand_subject() -> str:
    return f"{rand_word()}-{rand_hex(4)} {rand_word()}"


def rand_body() -> str:
    return " ".join(rand_word() for _ in range(random.randint(20, 80)))


def rand_name() -> str:
    return rand_word().capitalize()


# ------------------------------------------------------------------ tasks ---
# 每个任务只产生自建内容，不读取或改动任何真实用户数据。

def task_send_mail(token: str, user: str, peer: str) -> None:
    """随机发送一封全随机内容的邮件（Mail.Send 权限）。"""
    payload = {
        "message": {
            "subject": rand_subject(),
            "body": {"contentType": "Text", "content": rand_body()},
            "toRecipients": [{"emailAddress": {"address": peer}}],
        },
        "saveToSentItems": True,
    }
    call_api(token, "POST", f"/users/{user}/sendMail", json=payload)


def task_draft_mail(token: str, user: str, peer: str) -> None:
    """随机创建一封草稿邮件，不发送（Mail.ReadWrite 权限）。"""
    payload = {
        "subject": rand_subject(),
        "body": {"contentType": "Text", "content": rand_body()},
        "toRecipients": [{"emailAddress": {"address": peer}}],
    }
    call_api(token, "POST", f"/users/{user}/messages", json=payload)


def task_create_event(token: str, user: str, peer: str) -> None:
    """随机创建一个日历事件（Calendars.ReadWrite 权限）。"""
    start = datetime.now(timezone.utc) + timedelta(days=random.randint(1, 14),
                                                   hours=random.randint(8, 18))
    payload = {
        "subject": rand_subject(),
        "isReminderOn": False,
        "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"),
                  "timeZone": "UTC"},
        "end": {"dateTime": (start + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": "UTC"},
    }
    call_api(token, "POST", f"/users/{user}/events", json=payload)


def task_onedrive_upload(token: str, user: str, peer: str) -> None:
    """上传随机字节文件到自建目录 /daily-sync/（Files.ReadWrite.All 权限）。"""
    name = f"daily-sync/{rand_hex(8)}.bin"
    size = random.randint(1024, 256 * 1024)
    call_api(token, "PUT", f"/users/{user}/drive/root:/{name}:/content",
             data=os.urandom(size))


def task_onedrive_cleanup(token: str, user: str, peer: str) -> None:
    """清理自建目录 /daily-sync/ 中的部分文件，防止 drive 无限增长。

    仅枚举并删除该目录内的文件，不触碰任何其他路径；目录不存在时静默跳过。
    """
    try:
        resp = call_api(token, "GET",
                        f"/users/{user}/drive/root:/daily-sync:/children?$top=50&$select=id")
    except RuntimeError:
        return
    items = resp.json().get("value", [])
    if not items:
        return
    for item in random.sample(items, k=random.randint(1, min(5, len(items)))):
        call_api(token, "DELETE", f"/users/{user}/drive/items/{item['id']}")


def task_create_contact(token: str, user: str, peer: str) -> None:
    """随机创建一个随机姓名的联系人（Contacts.ReadWrite 权限）。"""
    payload = {
        "givenName": rand_name(),
        "surname": rand_name(),
        "displayName": f"{rand_name()} {rand_name()}",
        "emailAddresses": [{"address": f"{rand_word()}@{rand_word()}.example"}],
    }
    call_api(token, "POST", f"/users/{user}/contacts", json=payload)


TASKS = {
    "send_mail": task_send_mail,
    "draft_mail": task_draft_mail,
    "create_event": task_create_event,
    "onedrive_upload": task_onedrive_upload,
    "onedrive_cleanup": task_onedrive_cleanup,
    "create_contact": task_create_contact,
}
TASK_WEIGHTS = {
    "send_mail": 5,
    "draft_mail": 3,
    "create_event": 3,
    "onedrive_upload": 4,
    "onedrive_cleanup": 2,
    "create_contact": 2,
}


# ------------------------------------------------------------------- main ---

def load_enabled_tasks() -> list:
    """从 config.json 读取启用的任务类型，缺失或非法时回退为全部任务。"""
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            enabled = json.load(fh).get("tasks", [])
        valid = [t for t in enabled if t in TASKS]
        if valid:
            return valid
    except (OSError, ValueError):
        pass
    return list(TASKS)


def main() -> int:
    try:
        for key in ("TENANT_ID", "CLIENT_ID", "CLIENT_SECRET"):
            os.environ[key]
        users = [u.strip() for u in os.environ.get("TARGET_USERS", "").split(",") if u.strip()]
    except KeyError as exc:
        log(f"missing env: {exc}")
        return 1
    if len(users) < 1:
        log("TARGET_USERS is empty")
        return 1

    global REDACT
    REDACT = make_redactor(users)

    token = get_token()
    log(f"token acquired, {len(users)} target user(s)")

    enabled = load_enabled_tasks()
    log(f"task pool: {enabled}")

    executed = 0
    picked = random.sample(enabled, k=random.randint(min(4, len(enabled)), len(enabled)))
    for name in picked:
        for _ in range(random.randint(1, TASK_WEIGHTS.get(name, 2))):
            actor = random.choice(users)
            peer = random.choice(users)
            try:
                TASKS[name](token, actor, peer)
                executed += 1
            except RuntimeError as exc:
                log(f"task {name} failed: {REDACT(str(exc))}")
            time.sleep(random.uniform(1, 4))

    log(f"done, {executed} API activities generated")
    return 0 if executed else 1


if __name__ == "__main__":
    sys.exit(main())