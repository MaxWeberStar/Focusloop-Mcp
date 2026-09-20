# FocusLoop

**FocusLoop** 是一个本地 MCP Server，帮助 AI Agent 在长任务中持续服务于用户的目标——当 AI 的方向偏离时，主动提醒用户确认。

> **AI 越聪明，用户越不能丢判断。**

## 解决的问题

AI 在多轮对话中常见的三类"注意力漂移"：

| 类型 | 描述 |
|------|------|
| **目标替换** | AI 不知不觉把任务换成了另一个 |
| **范围扩大** | AI 每次加一点，最后规模远超预期 |
| **决策遗忘** | 你否决过的方向，AI 过几天又提 |

## 快速开始

```bash
git clone https://github.com/MaxWeberStar/Focusloop-Mcp.git
cd Focusloop-Mcp/shadow
uv sync
python focusloop.py propose example_goal.json --source "my goal"
python focusloop.py confirm 1 --expected 0 --source "user confirmed"
```

接入 Claude Code / Trae：创建 `.mcp.json`：
```json
{
  "mcpServers": {
    "focusloop": {
      "command": "python",
      "args": ["-m", "focusloop_mcp_server"],
      "env": {
        "FOCUSLOOP_DB": ".focusloop/state.sqlite3",
        "FOCUSLOOP_PROJECT": "my-project"
      }
    }
  }
}
```

## 效果数据

| 指标 | 值 |
|------|----|
| Drift Recall | **90.9%** |
| 误报率（GOAL 完整时）| **< 10%** |

详见 `02_PRD_草案.md` §8。

## 许可证

MIT License
