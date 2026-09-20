"""CLI：在目标确认前检查范围、约束、验收、阶段四维度。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from goal_completeness import check_goal_completeness

def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("focusloop_goal.json")
    result = check_goal_completeness(json.loads(path.read_text(encoding="utf-8")))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["complete"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
