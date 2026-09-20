"""目标四维完整性预防检查 v2：增加前置阶段和内部矛盾检测。"""
from __future__ import annotations

import re
from typing import Any

DIMENSIONS = {
    "scope": ("范围", ("objective", "deliverables", "non_goals")),
    "dev_activities": ("开发活动", ("dev_activities",)),
    "constraints": ("约束", ("constraints",)),
    "acceptance": ("验收", ("acceptance", "acceptance_criteria")),
    "stage": ("阶段", ("stage", "milestones", "phases")),
}

# 前置阶段指示词（出现任意一个，说明可能需要前置阶段）
PREPHASE_KEYWORDS = [
    "调研", "研究", "分析", "验证", "探索", "试点",
    "调研报告", "可行性", "概念验证", "POC",
    "investigation", "research", "analysis", "validation",
]

# 内部矛盾检测：non_goals 中出现但在 deliverables/objective 中也出现的内容
CONTRADICTION_PATTERNS = [
    ("多宿主", ["多平台", "跨平台", "Trae", "Hermes", "Codex", "Cursor"]),
    ("插件", ["插件", "plugin"]),
]


def _check_prephase_completeness(goal: dict[str, Any]) -> dict[str, Any]:
    """检查目标是否可能需要前置阶段但未定义。"""
    objective = goal.get("objective", "")
    deliverables = goal.get("deliverables", [])
    all_text = objective + " " + " ".join(deliverables)
    all_lower = all_text.lower()

    found_prephases = [kw for kw in PREPHASE_KEYWORDS if kw.lower() in all_lower]
    
    # 检查是否有前置阶段定义
    stage = goal.get("stage", "")
    milestones = goal.get("milestones", [])
    phases = goal.get("phases", [])
    has_prephase_def = any([stage, milestones, phases])

    if found_prephases and not has_prephase_def:
        return {
            "has_prephase_risk": True,
            "indicators": found_prephases,
            "message": f"目标中出现前置阶段指示词 {found_prephases}，但未定义 stage/milestones/phases，建议补充",
        }
    return {"has_prephase_risk": False, "indicators": [], "message": None}


def _check_internal_contradictions(goal: dict[str, Any]) -> list[dict[str, Any]]:
    """检测 deliverables/objective 与 non_goals 之间的潜在矛盾。"""
    contradictions = []
    non_goals = goal.get("non_goals", [])
    deliverables = goal.get("deliverables", [])
    objective = goal.get("objective", "")
    all_text = (objective + " " + " ".join(deliverables)).lower()

    for ng in non_goals:
        ng_lower = ng.lower()
        for ng_keyword, conflict_terms in CONTRADICTION_PATTERNS:
            if ng_keyword.lower() in ng_lower:
                for term in conflict_terms:
                    if term.lower() in all_text:
                        contradictions.append({
                            "non_goal": ng,
                            "conflict_term": term,
                            "message": f"non_goals 包含「{ng_keyword}」，但 deliverables/objective 包含「{term}」，存在内部矛盾",
                        })
    return contradictions


def check_goal_completeness(goal: dict[str, Any]) -> dict[str, Any]:
    """
    四维完整性检查 + 前置阶段风险 + 内部矛盾检测。

    Returns:
        {
            "complete": bool,               # 四维是否全部完整
            "missing": list[str],           # 缺失的维度
            "dimensions": dict,             # 各维度状态
            "prephase": dict,              # 前置阶段风险
            "contradictions": list[dict],   # 内部矛盾列表
            "warnings": list[str],          # 所有警告汇总
        }
    """
    # 基础四维检查
    dimensions: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for key, (label, fields) in DIMENSIONS.items():
        present = next((field for field in fields if goal.get(field)), None)
        dimensions[key] = {"label": label, "complete": present is not None, "field": present}
        if present is None:
            missing.append(key)

    # 前置阶段检查
    prephase = _check_prephase_completeness(goal)

    # 内部矛盾检查
    contradictions = _check_internal_contradictions(goal)

    # 汇总警告
    warnings: list[str] = []
    if prephase["has_prephase_risk"]:
        warnings.append(prephase["message"])
    for c in contradictions:
        warnings.append(c["message"])

    return {
        "complete": not missing,
        "missing": missing,
        "dimensions": dimensions,
        "prephase": prephase,
        "contradictions": contradictions,
        "warnings": warnings,
    }


if __name__ == "__main__":
    import json, sys
    from pathlib import Path

    goal_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("focusloop_goal.json")
    goal = json.loads(goal_path.read_text())
    result = check_goal_completeness(goal)
    print(json.dumps(result, ensure_ascii=False, indent=2))


# ── 典型开发活动清单 ──────────────────────────────────────
# 这些活动是任何项目都会做的，但在 end deliverables 中容易被忽略
# GOAL 应至少包含项目特有的开发活动

TYPICAL_DEV_ACTIVITIES = {
    # 工程验证类
    "pytest 测试": ["pytest", "测试", "验证", "回归测试", "单元测试", "test", "testing"],
    "开发环境验证": ["环境配置", "环境验证", "CLI 工具可用", "登录验证", "setup", "environment"],
    "文档维护": ["README", "文档", "更新文档", "doc", "documentation"],
    "PRD/目标维护": ["PRD 更新", "目标文件更新", "roadmap 更新"],
    # 质量保障类
    "规则迭代": ["规则更新", "规则修复", "补充规则", "rules.json"],
    "安全规则修复": ["安全规则", "阻断规则", "g2-", "rule patch"],
    # 工程实践类
    "Shell 脚本开发": ["shell 脚本", "run_", ".sh 脚本", "bash script"],
    "配置验证": ["配置验证", "config validation", "settings check"],
    # 跨平台验证
    "多平台适配验证": ["Trae", "Hermes", "Codex", "Cursor", "adapter", "多平台"],
    "MCP Server 验证": ["MCP", "stdio", "tools/list", "mcp server"],
}

# 从典型活动反向推导：给定 GOAL 缺失的活动建议
def suggest_missing_activities(
    goal_text: str,
    current_deliverables: list[str],
    typical: dict[str, list[str]] = TYPICAL_DEV_ACTIVITIES,
) -> list[dict[str, str]]:
    """检测 GOAL 文本中缺少哪些典型开发活动，返回建议列表。"""
    all_text = (goal_text + " " + " ".join(current_deliverables)).lower()
    suggestions = []
    for activity, keywords in typical.items():
        # 检查是否已有该活动的指示
        covered = any(kw.lower() in all_text for kw in keywords)
        if not covered:
            # 按关键词匹配度推断相关性
            relevance = sum(1 for kw in keywords if kw.lower() in all_text) / len(keywords)
            if relevance > 0:  # 至少有一个相关关键词
                suggestions.append({
                    "activity": activity,
                    "relevance_score": round(relevance, 2),
                    "keywords_found": [kw for kw in keywords if kw.lower() in all_text],
                    "suggestion": f"建议将「{activity}」加入 deliverables 或 constraints",
                })
    # 按相关度排序
    suggestions.sort(key=lambda x: x["relevance_score"], reverse=True)
    return suggestions[:5]  # 最多返回 5 条


if __name__ == "__main__":
    import json, sys
    from pathlib import Path

    goal_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("focusloop_goal.json")
    goal = json.loads(goal_path.read_text())

    result = check_goal_completeness(goal)
    all_text = goal.get("objective", "") + " " + " ".join(goal.get("deliverables", []))
    suggestions = suggest_missing_activities(all_text, goal.get("deliverables", []))

    print(json.dumps({
        "completeness": result,
        "suggestions": suggestions,
    }, ensure_ascii=False, indent=2))
