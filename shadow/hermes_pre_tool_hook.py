"""Hermes pre_tool_call hook：用 Gate 2 检查 Hermes 即将执行的工具。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from gate2.checker import Gate2Checker

def main() -> int:
    payload = json.load(sys.stdin)
    tool_name = payload.get("tool_name") or ""
    # Hermes commonly names its shell tool terminal; Gate 2 rules use Bash.
    if tool_name.lower() in {"terminal", "shell", "bash"}:
        tool_name = "bash"
    tool_input = payload.get("tool_input") or payload.get("args") or {}
    rules_path = Path(os.environ.get("FOCUSLOOP_RULES", Path(__file__).parent / "gate2" / "rules.json"))
    result = Gate2Checker(rules_path).check(tool_name, tool_input)
    if result is None or result.action != "block":
        print("{}")
        return 0
    print(json.dumps({"action": "block", "message": result.user_message.format(match=result.matched_value)}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
