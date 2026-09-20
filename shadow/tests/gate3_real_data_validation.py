"""用当前 FocusLoop 开发记录做 Gate 3 标注回归。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gate3_drift import _three_tier_verdict, check_gate3

GOAL = {"objective": "完成 FocusLoop AI Work 项目", "deliverables": [
    "完成 FocusLoop Gate 1/2/3 统一 MCP Server", "完成真实开发影子验证",
    "完成 Trae IDE Gate 2 接入验证", "Gate 1 Gate 2 Gate 3 语义覆盖率 阈值 PRD 文档"]}
CASES = [
    (["Gate 1 Gate 2 Gate 3 统一 MCP Server"], "aligned"),
    (["Gate 1 Gate 2 动态规则 PRD 文档"], "ambiguous"),
    (["Trae IDE MCP gate2_check 真实接入"], "aligned"),
    (["Gate 3 语义覆盖率 阈值"], "aligned"),
    (["PRD 文档"], "aligned"),
    (["实现聊天系统 WebSocket 用户登录"], "drift"),
    (["制作宠物养成游戏和营销落地页"], "drift"),
]

def main() -> int:
    results = []
    for context, expected in CASES:
        report = check_gate3(GOAL, context, semantic=True)
        results.append({"context": context, "expected": expected, "actual": report.verdict,
                        "score": report.overlap_score, "thresholds": {"high": 0.65, "low": 0.30}})
    threshold_checks = [
        (0.70, "aligned"), (0.46, "ambiguous"), (0.10, "drift")
    ]
    for score, expected in threshold_checks:
        actual, _ = _three_tier_verdict(score, False, 0.65, 0.30)
        if actual != expected:
            failures.append({"score": score, "expected": expected, "actual": actual})
    print(json.dumps({"case_count": len(results), "results": results,
                      "threshold_checks": threshold_checks}, ensure_ascii=False, indent=2))
    failures = [row for row in results if row["actual"] != row["expected"]]
    print("PASS: all real-development labeled cases matched" if not failures else f"FAIL: {len(failures)} cases mismatched")
    return 0 if not failures else 1

if __name__ == "__main__":
    raise SystemExit(main())
