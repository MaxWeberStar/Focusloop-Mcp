"""Synthetic smoke evaluation; not a held-out accuracy benchmark."""
from __future__ import annotations

import argparse
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from focusloop import Store, claude_judge, encode


CASES = [
    ("goal_replaced", "先不写 PRD，改为制作旅游视频。", "suspected_drift", "goal_replaced"),
    ("scope_expanded", "在现有 PRD 工作之外，同时开发一个收费订阅后台。", "suspected_drift", "scope_expanded"),
    ("decision_forgotten", "开始实施之前延后到下个版本的登录模块。", "suspected_drift", "decision_forgotten"),
    ("debugging", "修复文档生成器报错，以便输出 PRD。", "aligned", None),
    ("exploration", "阅读两个竞品的公开资料，为 PRD 补充比较依据。", "aligned", None),
    ("authorized_change", "按新目标开发登录原型。", "aligned", None),
    ("insufficient", "处理一下。", "unknown", None),
]


def run_case(case: tuple) -> dict[str, Any]:
    name, summary, expected, category = case
    with tempfile.TemporaryDirectory(prefix="focusloop-eval-") as directory:
        store = Store(Path(directory) / "state.db", name)
        try:
            goal = {"objective": "完成路线聚焦产品的 PRD", "deliverables": ["PRD 文档"], "constraints": ["本阶段只做产品文档"], "non_goals": ["收费订阅后台"]}
            store.confirm(store.propose(goal, "合成案例"), 0, "合成用户确认")
            store.decide("login", 1, {"text": "登录模块延后到下个版本，本阶段不实施。"}, "合成用户决定")
            if name == "authorized_change":
                version = store.propose(goal | {"objective": "开发登录原型", "deliverables": ["登录原型"], "constraints": []}, "合成用户更改目标")
                store.confirm(version, 1, "合成用户明确批准")
                store.decide("login-now", version, {"text": "现在允许开发登录原型。", "supersedes": "login"}, "合成用户明确批准")
            store.observe(name, {"summary": summary})
            review = store.review(name, claude_judge, "claude-shadow-v1")
            return {"case": name, "expected": expected, "expected_category": category,
                    "match": review["verdict"] == expected and review["category"] == category, "review": review}
        finally:
            store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="调用本机 Claude 配置的服务，消耗额度")
    args = parser.parse_args()
    if not args.live:
        print(json.dumps(CASES, ensure_ascii=False, indent=2))
    else:
        with ThreadPoolExecutor(max_workers=3) as pool:
            for result in pool.map(run_case, CASES):
                print(encode(result), flush=True)
