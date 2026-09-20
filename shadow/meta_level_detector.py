"""
P2 元层次检测：路线确认请求频率监控。

触发条件（PRD §4 漂移判定标准）：
  用户在单个项目中提出路线确认请求 ≥ 2 次时，触发元层次检查。

元层次检查与 Gate 3 的区别：
  - Gate 3：检查当前工作内容是否在 deliverables/constraints/non_goals 范围内
  - 元层次：检查当前工作是否服务于原始 objective，以及是否存在路线关系表达问题

这不是漂移检测，而是"路线一致性"检查。
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from focusloop import Store


ROUTE_CONFIRM_KEYWORDS = [
    "路线确认", "确认路线", "我们到哪了", "当前路线",
    "是否偏离", "回到原来的", "不对", "不是这个",
    "目标是什么", "我们现在在做什么", "偏离了吗",
    "route confirm", "确认一下", "梳理一下路线",
    "我们是不是跑偏了", "我想要的是",
]


@dataclass
class MetaLevelReport:
    route_confirm_count: int
    threshold: int
    triggered: bool
    triggered_at: str | None
    meta_verdict: str  # "concerned" / "clear"
    reasoning: str
    recommendations: list[str]


def _detect_route_confirm_request(text: str) -> bool:
    """检测文本中是否包含路线确认请求。"""
    text_lower = text.lower()
    for kw in ROUTE_CONFIRM_KEYWORDS:
        if kw.lower() in text_lower:
            return True
    return False


def count_route_confirm_requests(store: Store) -> int:
    """从决策记录中统计路线确认请求次数。"""
    rows = store.db.execute(
        "SELECT payload FROM decisions WHERE project=?",
        (store.project,),
    ).fetchall()
    count = 0
    for row in rows:
        try:
            payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
            text = payload.get("text", "")
            if _detect_route_confirm_request(text):
                count += 1
        except Exception:
            pass
    return count


def _llm_meta_judge(objective: str, current_phase: str, route_confirm_count: int) -> dict[str, Any]:
    """用 LLM 做元层次判断（当前会话状态）。"""
    prompt = f"""你是一个项目路线分析师。当前用户在单个项目中已第 {route_confirm_count} 次要求路线确认。
    
原始目标：{objective}
当前所处阶段或最近工作：{current_phase}

请分析：
1. 当前路线是否明显偏离原始目标？
2. 是否存在"阶段关系表达不清"的问题（助手在推进前未说明与原路线的关系）？
3. 用户多次要求确认的根本原因是什么？

请返回 JSON：
{{"verdict": "concerned" 或 "clear", "reasoning": "...", "recommendations": ["建议1", "建议2"]}}
"""
    try:
        with tempfile.TemporaryDirectory(prefix="focusloop-meta-") as directory:
            completed = subprocess.run(
                ["claude", "--safe-mode", "-p", "--tools", "", "--strict-mcp-config",
                 "--no-session-persistence", "--output-format", "json",
                 "--json-schema", '{"type":"object","properties":{"verdict":{"type":"string"},"reasoning":{"type":"string"},"recommendations":{"type":"array","items":{"type":"string"}}},"required":["verdict","reasoning","recommendations"]}'],
                input=prompt, text=True, capture_output=True, cwd=directory, timeout=30,
            )
        if completed.returncode == 0:
            return json.loads(completed.stdout)
    except Exception:
        pass
    return {
        "verdict": "unknown",
        "reasoning": "元层次判断失败（LLM 不可用），请用户手动确认当前路线",
        "recommendations": ["请在 focusloop status 中手动确认当前目标是否正确"],
    }


def check_meta_level(
    store: Store,
    current_text: str = "",
    threshold: int = 2,
    use_llm: bool = True,
) -> MetaLevelReport:
    """
    元层次检测主入口。

    检查逻辑：
    1. 统计历史上路线确认请求次数（含当前输入）
    2. 超过阈值时触发元层次检查
    3. 结合当前目标和阶段做判断
    """
    from datetime import datetime, timezone

    current_goal = store.current()
    objective = current_goal["payload"].get("objective", "") if current_goal else "未设定目标"
    stage = current_goal["payload"].get("stage", "") if current_goal else ""
    current_phase = current_text or stage or "未知"

    # 统计路线确认请求（含当前文本）
    historical_count = count_route_confirm_requests(store)
    current_is_confirm = _detect_route_confirm_request(current_text)
    total_count = historical_count + (1 if current_is_confirm else 0)

    triggered = total_count >= threshold
    triggered_at = datetime.now(timezone.utc).isoformat() if triggered else None

    if triggered:
        verdict_data = _llm_meta_judge(objective, current_phase, total_count)
        meta_verdict = verdict_data.get("verdict", "unknown")
        reasoning = verdict_data.get("reasoning", "")
        recommendations = verdict_data.get("recommendations", [])
    else:
        meta_verdict = "clear"
        reasoning = f"路线确认请求 {total_count}/{threshold} 次，尚未触发元层次检查"
        recommendations = []

    return MetaLevelReport(
        route_confirm_count=total_count,
        threshold=threshold,
        triggered=triggered,
        triggered_at=triggered_at,
        meta_verdict=meta_verdict,
        reasoning=reasoning,
        recommendations=recommendations,
    )


def record_route_confirm_decision(store: Store, text: str, source: str) -> None:
    """将路线确认请求记录为决策（供下次统计使用）。"""
    if _detect_route_confirm_request(text):
        store.decide(
            event_id=f"route_confirm_{int(store.db.execute('SELECT COUNT(*)+1 FROM decisions WHERE project=?', (store.project,)).fetchone()[0])}",
            expected=store.version(),
            payload={"text": text, "kind": "route_confirm_request"},
            source=source,
        )


if __name__ == "__main__":
    import sys
    from pathlib import Path

    db_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".focusloop/state.sqlite3")
    project = sys.argv[3] if len(sys.argv) > 3 else "focusloop-v1"

    store = Store(db_path, project)
    try:
        current_text = sys.argv[1] if len(sys.argv) > 1 else ""
        result = check_meta_level(store, current_text)
        print(json.dumps({
            "route_confirm_count": result.route_confirm_count,
            "threshold": result.threshold,
            "triggered": result.triggered,
            "triggered_at": result.triggered_at,
            "meta_verdict": result.meta_verdict,
            "reasoning": result.reasoning,
            "recommendations": result.recommendations,
        }, ensure_ascii=False, indent=2))
    finally:
        store.close()
