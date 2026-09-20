"""
FocusLoop MCP Server v1
使用 MCP SDK v2 (mcp.server.mcpserver)

支持 Herme/Trae/DeepSeek Harness/Claude Code/Codex 的 MCP 客户端接入

启动方式（stdio）：
    python -m gate2.mcp_server

Trae 配置（.trae/mcp.json）：
    {
      "mcpServers": {
        "focusloop": {
          "command": "python",
          "args": ["-m", "gate2.mcp_server"],
          "env": {
            "FOCUSLOOP_DB": ".focusloop/state.sqlite3"
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

# 确保 gate2 模块可导入
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.mcpserver import MCPServer
from mcp.types import Tool, TextContent
from mcp.server.mcpserver.context import Context


def _get_rules_path() -> Path:
    env = os.getenv("FOCUSLOOP_RULES", "")
    if env:
        return Path(env)
    return Path(__file__).parent / "rules.json"


def _get_db_path() -> Path:
    env = os.getenv("FOCUSLOOP_DB", "")
    if env:
        return Path(env).expanduser()
    return Path(__file__).parent.parent / ".focusloop" / "state.sqlite3"


# ── MCP Server 实例 ──────────────────────────────────────────

server = MCPServer(
    name="focusloop",
    version="1.0.0",
    description="FocusLoop: AI 目标锚定与路线纠偏",
)


# ── 工具实现 ────────────────────────────────────────────────

@server.tool(
    name="gate2_check",
    description="检查工具调用是否触发 FocusLoop 闸口2规则。闸口2专注于隐私和规则破坏检测：数据外传、包安装、文件删除、宿主绑定等危险操作。",
)
def gate2_check(tool_name: str, tool_input: dict) -> str:
    """
    Args:
        tool_name: 工具名称（如 "Bash", "Write", "npm"）
        tool_input: 工具参数字典
    """
    from gate2.checker import Gate2Checker

    rules_path = _get_rules_path()
    checker = Gate2Checker(rules_path)
    result = checker.check(tool_name, tool_input)

    if result is None:
        return json.dumps({
            "status": "passed",
            "message": "✅ 通过 FocusLoop 闸口2检查",
            "tool": tool_name,
        }, ensure_ascii=False)

    if result.action == "block":
        msg = result.user_message.format(match=result.matched_value)
        return json.dumps({
            "status": "blocked",
            "action": "block",
            "reason": msg,
            "rule_id": result.rule_id,
            "severity": result.severity,
            "category": result.category,
            "tool": tool_name,
        }, ensure_ascii=False)

    # action == "log"
    return json.dumps({
        "status": "logged",
        "rule_id": result.rule_id,
        "category": result.category,
        "tool": tool_name,
    }, ensure_ascii=False)


@server.tool(
    name="goal_status",
    description="获取当前项目的 FocusLoop 目标状态、版本和约束列表",
)
def goal_status() -> str:
    """返回当前已确认目标的 JSON 摘要"""
    db_path = _get_db_path()
    project = os.getenv("FOCUSLOOP_PROJECT", "focusloop-v1")

    if not db_path.exists():
        return json.dumps({
            "status": "no_project",
            "message": f"数据库不存在: {db_path}",
            "hint": "请先运行: python focusloop.py propose <goal.json> --source <来源>"
        }, ensure_ascii=False)

    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from focusloop import Store

        store = Store(db_path, project)
        current = store.current()
        store.close()

        if current is None:
            return json.dumps({
                "status": "no_goal",
                "message": "尚无已确认目标"
            }, ensure_ascii=False)

        payload = current["payload"]
        return json.dumps({
            "status": "ok",
            "version": current["version"],
            "source": current["source"],
            "objective": payload.get("objective"),
            "deliverables": payload.get("deliverables", []),
            "constraints": payload.get("constraints", []),
            "non_goals": payload.get("non_goals", []),
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False)


@server.tool(
    name="list_constraints",
    description="列出 FocusLoop 闸口2当前加载的所有规则",
)
def list_constraints(category: str | None = None) -> str:
    """列出规则，可选按 category 过滤"""
    from gate2.checker import Gate2Checker

    rules_path = _get_rules_path()
    checker = Gate2Checker(rules_path)

    rules = checker.list_rules(category=category)
    cats = checker.list_categories()

    return json.dumps({
        "count": len(rules),
        "categories": cats,
        "rules": [
            {
                "id": r["id"],
                "category": r["category"],
                "severity": r["severity"],
                "action": r["action"],
                "tool": r["tool"],
                "description": r["user_message"].split("：")[0] if "：" in r["user_message"] else r["user_message"],
            }
            for r in rules
        ],
    }, ensure_ascii=False, indent=2)


@server.tool(
    name="add_rule",
    description="动态添加闸口2规则（需谨慎，规则会立即生效）",
)
def add_rule(
    rule_id: str,
    pattern: str,
    tool: str = "*",
    severity: str = "medium",
    action: str = "block",
    message: str = "检测到异常操作，是否继续？",
    category: str = "user_defined",
    arg_key: str | None = "command",
) -> str:
    """动态添加规则"""
    from gate2.checker import Gate2Checker

    rules_path = _get_rules_path()
    checker = Gate2Checker(rules_path)

    rule = {
        "id": rule_id,
        "category": category,
        "pattern": pattern,
        "tool": tool,
        "arg_key": arg_key,
        "severity": severity,
        "action": action,
        "user_message": message,
        "constraint_ref": None,
    }

    try:
        added = checker.add_rule(rule)
        return json.dumps({
            "status": "added",
            "rule_id": added,
            "message": f"规则 {added} 已添加"
        }, ensure_ascii=False)
    except ValueError as e:
        return json.dumps({
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False)


# ── 入口 ───────────────────────────────────────────────────

def main() -> None:
    print("# FocusLoop MCP Server v1", file=sys.stderr)
    print(f"# 规则: {_get_rules_path()}", file=sys.stderr)
    print(f"# 数据库: {_get_db_path()}", file=sys.stderr)
    print(f"# 项目: {os.getenv('FOCUSLOOP_PROJECT', 'focusloop-v1')}", file=sys.stderr)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
