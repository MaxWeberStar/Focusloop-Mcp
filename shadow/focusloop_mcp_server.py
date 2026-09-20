"""
FocusLoop 统一 MCP Server v2

统一暴露 Gate 1 / 1.5 / 2 / 3 能力给所有平台：
- Gate 1: 约束提取、确认、拒绝、列出
- Gate 2: 规则检查、动态规则同步、规则管理
- Gate 3: 漂移检测（三档判定）
- Goal: 目标提案、确认（需用户执行）、状态查询

启动方式（stdio）：
    python -m focusloop_mcp_server

环境变量：
    FOCUSLOOP_DB       - SQLite 数据库路径（默认 .focusloop/state.sqlite3）
    FOCUSLOOP_PROJECT  - 项目名（默认 focusloop-v1）
    FOCUSLOOP_RULES    - Gate 2 规则文件路径（默认 gate2/rules.json）

平台接入配置示例（Trae .trae/mcp.json / Claude Code .mcp.json）:
    {
      "mcpServers": {
        "focusloop": {
          "command": "python",
          "args": ["-m", "focusloop_mcp_server"],
          "env": {
            "FOCUSLOOP_DB": ".focusloop/state.sqlite3",
            "FOCUSLOOP_PROJECT": "focusloop-v1"
          }
        }
      }
    }
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# 确保 gate2 / 当前目录可导入
sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.mcpserver import MCPServer
from mcp.types import TextContent
from gate2.checker import Gate2Checker
from goal_completeness import check_goal_completeness, suggest_missing_activities
from meta_level_detector import check_meta_level


def _get_db_path() -> Path:
    env = os.getenv("FOCUSLOOP_DB", "")
    if env:
        return Path(env).expanduser()
    return Path(__file__).parent / ".focusloop" / "state.sqlite3"


def _get_rules_path() -> Path:
    env = os.getenv("FOCUSLOOP_RULES", "")
    if env:
        return Path(env)
    return Path(__file__).parent / "gate2" / "rules.json"


def _get_project() -> str:
    return os.getenv("FOCUSLOOP_PROJECT", "focusloop-v1")


# ── MCP Server 实例 ──────────────────────────────────────

server = MCPServer(
    name="focusloop",
    version="2.0.0",
    description="FocusLoop: AI 目标锚定与路线纠偏 (Gate 1/1.5/2/3 统一)",
)


# ── 通用工具 ─────────────────────────────────────────────

def _get_store():
    """获取当前项目的 Store 实例（每个调用新建一个避免跨调用状态）。"""
    from focusloop import Store
    return Store(_get_db_path(), _get_project())


def _get_gate2_checker(store):
    from gate2.checker import Gate2Checker
    checker = Gate2Checker(_get_rules_path(), store=store)
    checker.sync_from_store()
    return checker


def _ok(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


# ════════════════════════════════════════════════════════════
# Gate 0 — Goal Management
# ════════════════════════════════════════════════════════════

@server.tool(
    name="goal_status",
    description="获取当前项目已确认目标（版本、来源、约束、非目标列表）。任何 gate 检查都依赖于此。",
)
def goal_status() -> str:
    db_path = _get_db_path()
    if not db_path.exists():
        return _ok({"status": "no_project", "hint": "请先 propose 一个目标"})
    store = _get_store()
    try:
        current = store.current()
        if not current:
            return _ok({"status": "no_goal", "hint": "尚无已确认目标"})
        payload = current["payload"]
        return _ok({
            "status": "ok",
            "version": current["version"],
            "source": current["source"],
            "objective": payload.get("objective"),
            "deliverables": payload.get("deliverables", []),
            "constraints": payload.get("constraints", []),
            "non_goals": payload.get("non_goals", []),
        })
    finally:
        store.close()


@server.tool(
    name="goal_propose",
    description="Agent 提议一个新目标版本。Agent 不能 confirm，必须由用户执行 goal_confirm。",
)
def goal_propose(payload: dict, source: str) -> str:
    store = _get_store()
    try:
        v = store.propose(payload, source)
        return _ok({
            "status": "proposed",
            "version": v,
            "hint": f"请用户执行 focusloop confirm {v} --expected {v - 1 if v > 1 else 0} --source 用户确认",
        })
    except ValueError as e:
        return _ok({"status": "error", "message": str(e)})
    finally:
        store.close()


@server.tool(
    name="goal_confirm",
    description="用户明确执行的目标确认（Agent 禁止自行调用）。返回 confirmed_version。",
)
def goal_confirm(version: int, expected: int, source: str) -> str:
    store = _get_store()
    try:
        store.confirm(version, expected, source)
        return _ok({"status": "confirmed", "version": version})
    except Exception as e:
        return _ok({"status": "error", "message": str(e)})
    finally:
        store.close()


# ════════════════════════════════════════════════════════════
# Gate 1 — Constraint Extraction & Confirmation
# ════════════════════════════════════════════════════════════

@server.tool(
    name="extract_constraints",
    description="从文本中提取候选约束（规则层，零模型依赖）。返回 ConstraintCandidate 列表。",
)
def extract_constraints(text: str, source: str = "mcp") -> str:
    from gate1_extractor import extract_from_text
    cands = extract_from_text(text, source=source, source_detail="mcp.extract_constraints")
    return _ok({
        "count": len(cands),
        "candidates": [c.to_dict() for c in cands],
    })


@server.tool(
    name="list_constraints",
    description="列出已确认 / 已拒绝 / 待审查的约束。默认全部。",
)
def list_constraints(status: str = "all") -> str:
    """status: all | confirmed | rejected | pending"""
    store = _get_store()
    try:
        confirmed_rows = store.db.execute(
            "SELECT id, payload FROM observations WHERE id LIKE ? ORDER BY created_at DESC",
            ("confirmed_constraint:%",)
        ).fetchall()
        rejected_rows = store.db.execute(
            "SELECT id, payload FROM observations WHERE id LIKE ? ORDER BY created_at DESC",
            ("rejected_constraint:%",)
        ).fetchall()
        pending_rows = store.db.execute(
            "SELECT id, payload FROM observations WHERE id LIKE ? ORDER BY created_at",
            ("constraint:%",)
        ).fetchall()

        confirmed_ids = {r[0].split(":", 1)[1] for r in confirmed_rows}
        rejected_ids = {r[0].split(":", 1)[1] for r in rejected_rows}

        confirmed = [json.loads(r[1]) for r in confirmed_rows]
        rejected = [json.loads(r[1]) for r in rejected_rows]
        pending = [
            json.loads(r[1]) for r in pending_rows
            if json.loads(r[1])["id"] not in confirmed_ids
            and json.loads(r[1])["id"] not in rejected_ids
        ]

        if status == "confirmed":
            return _ok({"constraints": confirmed})
        if status == "rejected":
            return _ok({"constraints": rejected})
        if status == "pending":
            return _ok({"constraints": pending})
        return _ok({
            "counts": {
                "confirmed": len(confirmed),
                "rejected": len(rejected),
                "pending": len(pending),
            },
            "confirmed": confirmed,
            "rejected": rejected,
            "pending": pending,
        })
    finally:
        store.close()


@server.tool(
    name="confirm_constraint",
    description="用户明确确认一条约束候选，纳入约束列表。会同步到 Gate 2 动态规则。",
)
def confirm_constraint(id: str, text: str, source: str, confidence: str = "medium") -> str:
    """confidence: high / medium / low"""
    store = _get_store()
    try:
        from gate1_extractor import ConstraintCandidate
        cand = ConstraintCandidate(
            id=id, text=text, source="confirmed",
            source_detail=source, confidence=confidence,
            matched_pattern="user_confirmed", auto_confirmed=False,
        )
        obs_id = "confirmed_constraint:" + id
        store.observe(obs_id, cand.to_dict())
        # 同步到 Gate 2
        checker = _get_gate2_checker(store)
        synced = len(checker._dynamic_rules)
        return _ok({
            "status": "confirmed",
            "id": id,
            "observation_id": obs_id,
            "gate2_dynamic_rules_count": synced,
        })
    finally:
        store.close()


@server.tool(
    name="reject_constraint",
    description="用户拒绝一条约束候选。会自动删除之前的 confirmed 记录（如果存在）。",
)
def reject_constraint(id: str, reason: str, source: str) -> str:
    import datetime as _dt
    store = _get_store()
    try:
        with store.db:
            store.db.execute(
                "DELETE FROM observations WHERE id = ?",
                ("confirmed_constraint:" + id,),
            )
        obs_id = "rejected_constraint:" + id
        store.observe(obs_id, {
            "id": id, "reason": reason, "source": source,
            "rejected_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        })
        return _ok({
            "status": "rejected",
            "id": id,
            "observation_id": obs_id,
            "removed_confirmed": True,
        })
    finally:
        store.close()


# ════════════════════════════════════════════════════════════
# Gate 1.5 — Semantic Expansion (via Gate 2 build)
# ════════════════════════════════════════════════════════════

@server.tool(
    name="expand_constraint",
    description="Gate 1.5 语义扩展：把约束文本扩展为多个同义词变体，生成宽松正则（用于 Gate 2 匹配）。",
)
def expand_constraint(text: str) -> str:
    from gate1_5_semantic import ConstraintExpander
    expander = ConstraintExpander()
    r = expander.expand(text)
    return _ok(r.to_dict())


# ════════════════════════════════════════════════════════════
# Gate 2 — Rule Engine
# ════════════════════════════════════════════════════════════

@server.tool(
    name="gate2_check",
    description="Gate 2 检查：判断工具调用是否触发隐私/规则破坏（数据外传、包安装、危险文件操作等）。",
)
def gate2_check(tool_name: str, tool_input: dict) -> str:
    store = _get_store()
    try:
        checker = _get_gate2_checker(store)
        result = checker.check(tool_name, tool_input)
        if result is None:
            return _ok({
                "status": "passed",
                "tool": tool_name,
                "dynamic_rules_loaded": len(checker._dynamic_rules),
            })
        msg = result.user_message.format(match=result.matched_value)
        return _ok({
            "status": result.action,
            "rule_id": result.rule_id,
            "category": result.category,
            "severity": result.severity,
            "reason": msg,
            "tool": tool_name,
            "constraint_ref": result.rule_ref,
        })
    except Exception as e:
        import traceback
        return _ok({
            "status": "error",
            "tool": tool_name,
            "error": str(e),
            "traceback": traceback.format_exc(),
        })
    finally:
        try:
            store.close()
        except Exception:
            pass


@server.tool(
    name="list_rules",
    description="列出 Gate 2 当前加载的所有规则（含静态 + 动态）。",
)
def list_rules(category: str | None = None, include_dynamic: bool = True) -> str:
    store = _get_store()
    try:
        checker = _get_gate2_checker(store)
        static_rules = checker.list_rules(category=category)
        result = {
            "static_rule_count": len(static_rules),
            "dynamic_rule_count": len(checker._dynamic_rules),
            "categories": checker.list_categories(),
            "static_rules": static_rules,
        }
        if include_dynamic:
            result["dynamic_rules"] = [
                {k: v for k, v in r.items()}  # 保留所有字段（含 _match_method 等）
                for r in checker._dynamic_rules
            ]
        return _ok(result)
    finally:
        store.close()


@server.tool(
    name="add_rule",
    description="动态添加 Gate 2 规则（谨慎使用，规则立即生效）。",
)
def add_rule(
    rule_id: str, pattern: str, tool: str = "*",
    severity: str = "medium", action: str = "block",
    message: str = "检测到异常操作，是否继续？",
    category: str = "user_defined", arg_key: str | None = "command",
) -> str:
    store = _get_store()
    try:
        checker = _get_gate2_checker(store)
        rule = {
            "id": rule_id, "category": category, "pattern": pattern,
            "tool": tool, "arg_key": arg_key, "severity": severity,
            "action": action, "user_message": message, "constraint_ref": None,
        }
        try:
            added = checker.add_rule(rule)
            return _ok({"status": "added", "rule_id": added})
        except ValueError as e:
            return _ok({"status": "error", "message": str(e)})
    finally:
        store.close()


@server.tool(
    name="sync_gate2",
    description="把 confirmed constraints 同步成 Gate 2 动态规则（使用 Gate 1.5 语义扩展）。返回生成的动态规则数。",
)
def sync_gate2() -> str:
    store = _get_store()
    try:
        checker = _get_gate2_checker(store)
        count = checker.sync_from_store()
        return _ok({
            "status": "synced",
            "synced_dynamic_rules": count,
            "dynamic_rules": [
                {
                    "id": r["id"],
                    "constraint_ref": r.get("constraint_ref"),
                    "match_method": r.get("_match_method", "literal"),
                    "variants_count": r.get("_variants_count", 1),
                    "semantic_tokens": r.get("_semantic_tokens", []),
                }
                for r in checker._dynamic_rules
            ],
        })
    finally:
        store.close()


# ════════════════════════════════════════════════════════════
# Gate 3 — Drift Detection
# ════════════════════════════════════════════════════════════

@server.tool(
    name="drift_check",
    description="Gate 3 漂移检测：检查当前实施内容是否偏离已确认目标。三档判定：aligned / ambiguous / drift。",
)
def drift_check(context: list[str], semantic: bool = False) -> str:
    """context: 当前实施内容列表（每个元素为一段文字）"""
    store = _get_store()
    try:
        current = store.current()
        if not current:
            return _ok({"status": "no_goal", "hint": "请先 propose+confirm 目标"})
        from gate3_drift import check_gate3
        rep = check_gate3(
            current["payload"], context,
            semantic=semantic,
        )
        return _ok(rep.to_dict())
    finally:
        store.close()


@server.tool(
    name="drift_review_plan",
    description="Gate 3 别名：与 drift_check 等价（保持向后兼容）。",
)
def drift_review_plan(context: list[str], semantic: bool = False) -> str:
    return drift_check(context, semantic)


# ════════════════════════════════════════════════════════════
# 跨闸口辅助
# ════════════════════════════════════════════════════════════

@server.tool(
    name="overview",
    description="一站式概览：目标状态 + 约束统计 + Gate 2 规则数 + Gate 3 摘要。适合初始化时快速了解全貌。",
)
def overview() -> str:
    store = _get_store()
    try:
        # Goal
        goal = store.current()
        goal_summary = None
        if goal:
            goal_summary = {
                "version": goal["version"],
                "objective": goal["payload"].get("objective"),
                "deliverables_count": len(goal["payload"].get("deliverables", [])),
            }

        # Constraints
        confirmed = store.db.execute(
            "SELECT COUNT(*) FROM observations WHERE id LIKE ?",
            ("confirmed_constraint:%",),
        ).fetchone()[0]
        rejected = store.db.execute(
            "SELECT COUNT(*) FROM observations WHERE id LIKE ?",
            ("rejected_constraint:%",),
        ).fetchone()[0]
        pending = store.db.execute(
            "SELECT COUNT(*) FROM observations WHERE id LIKE ?",
            ("constraint:%",),
        ).fetchone()[0]

        # Gate 2 rules
        checker = _get_gate2_checker(store)
        static_n = len(checker.list_rules())
        dynamic_n = len(checker._dynamic_rules)

        # Decisions / reviews
        decisions = store.db.execute(
            "SELECT COUNT(*) FROM decisions WHERE project=?", (store.project,)
        ).fetchone()[0]

        # Meta-level 检测
        try:
            meta = check_meta_level(store, current_text="", threshold=2, use_llm=False)
            meta_summary = {
                "route_confirm_count": meta.route_confirm_count,
                "threshold": meta.threshold,
                "triggered": meta.triggered,
                "meta_verdict": meta.meta_verdict,
                "reasoning": meta.reasoning,
            }
        except Exception:
            meta_summary = {"error": "meta_level 检测失败"}

        # GOAL 完整性
        if goal:
            gc = check_goal_completeness(goal["payload"])
            completeness_summary = {
                "complete": gc["complete"],
                "missing_dimensions": gc["missing"],
                "warnings": gc.get("warnings", []),
                "prephase_risk": gc["prephase"]["has_prephase_risk"],
                "contradictions": len(gc.get("contradictions", [])),
            }
        else:
            completeness_summary = None

        return _ok({
            "goal": goal_summary,
            "constraints": {
                "confirmed": confirmed,
                "rejected": rejected,
                "pending": pending,
            },
            "gate2_rules": {
                "static": static_n,
                "dynamic": dynamic_n,
            },
            "decisions": decisions,
            "meta_level": meta_summary,
            "goal_completeness": completeness_summary,
        })
    finally:
        store.close()


# ── 入口 ──────────────────────────────────────────────────

def main() -> None:
    print("# FocusLoop MCP Server v2 (unified)", file=sys.stderr)
    print(f"# 规则: {_get_rules_path()}", file=sys.stderr)
    print(f"# 数据库: {_get_db_path()}", file=sys.stderr)
    print(f"# 项目: {_get_project()}", file=sys.stderr)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
