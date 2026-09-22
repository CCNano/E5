#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily Config Sync Script

每日由 GitHub Actions (config-sync.yml) 运行，随机化两处配置后提交回仓库:
    1. .github/workflows/daily-tasks.yml -> 两条 cron 运行时间（每日不同）
    2. config.json                        -> 启用的 API 任务类型子集（每日不同）

schedule 触发的 workflow 总是使用默认分支上的最新文件，因此次日
Daily Tasks 会按新的时间与新任务池运行。本脚本不接触任何敏感信息。
"""

import json
import os
import random
import re
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
WF = os.path.join(ROOT, ".github", "workflows", "daily-tasks.yml")
CFG = os.path.join(ROOT, "config.json")

SAFE_TASKS = ["send_mail", "draft_mail", "create_event",
              "onedrive_upload", "onedrive_cleanup", "create_contact"]
CRON_RE = re.compile(r"(-\s*cron:\s*')([^']+)(')")


def rand_cron(hour_lo: int, hour_hi: int) -> str:
    return f"{random.randint(0, 59)} {random.randint(hour_lo, hour_hi)} * * *"


def rotate_workflow() -> list:
    """随机重写 daily-tasks.yml 中的两条 cron，返回新时间列表。"""
    with open(WF, encoding="utf-8") as fh:
        text = fh.read()
    crons = [rand_cron(1, 11), rand_cron(12, 22)]
    counter = {"i": 0}

    def repl(match: re.Match) -> str:
        i = counter["i"]
        counter["i"] += 1
        return f"{match.group(1)}{crons[i]}{match.group(3)}" if i < len(crons) else match.group(0)

    text, n = CRON_RE.subn(repl, text)
    if n != 2:
        raise RuntimeError(f"expected 2 cron lines in {WF}, found {n}")
    with open(WF, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return crons


def refresh_config() -> list:
    """随机挑选任务类型子集写入 config.json，返回启用的任务列表。"""
    tasks = random.sample(SAFE_TASKS, k=random.randint(4, len(SAFE_TASKS)))
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tasks": tasks,
    }
    with open(CFG, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    return tasks


def main() -> None:
    crons = rotate_workflow()
    tasks = refresh_config()
    print(f"refreshed cron -> {crons}")
    print(f"refreshed task pool -> {tasks}")


if __name__ == "__main__":
    main()