"""从事件流自动生成审查摘要，排除日志、中间调试和历史对话。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def summarize_recent_events(
    db_path: Path,
    project: str,
    since_observation_id: str | None = None,
    max_events: int = 20,
) -> dict[str, Any]:
    """
    从最近的 hook 事件中生成精简摘要。
    
    返回：
    {
      "summary": "自然语言描述",
      "user_request": "本轮用户明确请求",
      "tools_invoked": [{"tool": "Write", "target": "file.py"}, ...],
      "stage_artifacts": ["新文件 x.py", "修改 y.md"],
      "event_count": 实际事件数
    }
    """
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    
    # 找到起点
    if since_observation_id:
        cutoff_row = db.execute(
            "SELECT created_at FROM observations WHERE project=? AND id=? ORDER BY created_at DESC LIMIT 1",
            (project, since_observation_id)
        ).fetchone()
        cutoff = cutoff_row["created_at"] if cutoff_row else "1970-01-01T00:00:00+00:00"
    else:
        cutoff = "1970-01-01T00:00:00+00:00"
    
    # 读取最近事件
    rows = db.execute(
        """SELECT id, payload, created_at FROM observations 
           WHERE project=? AND created_at>? 
           ORDER BY created_at DESC LIMIT ?""",
        (project, cutoff, max_events)
    ).fetchall()
    
    db.close()
    
    if not rows:
        return {
            "summary": "尚无新增事件",
            "user_request": None,
            "tools_invoked": [],
            "stage_artifacts": [],
            "event_count": 0
        }
    
    # 倒序处理（时间正序）
    events = [json.loads(r["payload"]) for r in reversed(rows)]
    
    # 提取最后一次用户输入
    user_request = None
    for evt in reversed(events):
        if evt.get("event") == "UserPromptSubmit":
            user_request = "用户提交了新请求"
            break
    
    # 提取工具调用
    tools_invoked = []
    seen_tool_ids = set()
    for evt in events:
        if evt.get("event") in ("PreToolUse", "PostToolUse"):
            tool_id = evt.get("tool_use_id")
            tool_name = evt.get("tool")
            if tool_id and tool_id not in seen_tool_ids and tool_name:
                tools_invoked.append({"tool": tool_name, "tool_use_id": tool_id})
                seen_tool_ids.add(tool_id)
    
    # 生成自然语言摘要
    summary_parts = []
    if user_request:
        summary_parts.append("用户提交了新请求")
    if tools_invoked:
        tool_names = [t["tool"] for t in tools_invoked]
        summary_parts.append(f"调用了 {len(tool_names)} 个工具：{', '.join(tool_names)}")
    
    summary = "；".join(summary_parts) if summary_parts else "记录了元数据但无明确行动"
    
    return {
        "summary": summary,
        "user_request": user_request,
        "tools_invoked": tools_invoked,
        "stage_artifacts": [f"调用 {t['tool']}" for t in tools_invoked],
        "event_count": len(events)
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("用法: python3 summarize.py <db_path> <project> [since_observation_id]")
        sys.exit(1)
    
    result = summarize_recent_events(
        Path(sys.argv[1]),
        sys.argv[2],
        sys.argv[3] if len(sys.argv) > 3 else None
    )
    print(encode(result))
