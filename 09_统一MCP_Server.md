# FocusLoop 统一 MCP Server

**当前验收状态：✅ 已完成**

- MCP SDK 已声明为项目依赖：`mcp==2.2.0`（见 `shadow/pyproject.toml` 与 `shadow/uv.lock`）
- 真实开发影子验证已通过：Gate 2 阻断/放行、Gate 3 三档判定及完整开发周期均有回归结果
- `rules check` CLI、统一 MCP Server stdio JSON-RPC、Claude Code/Codex 配置生成均已验证

**日期**：2026-09-20  
**状态**：✅ 实现完成并通过 stdio JSON-RPC 测试  
**入口**：`focusloop_mcp_server.py`（统一暴露 Gate 1/1.5/2/3 + Goal 管理）

## 设计目标

将 FocusLoop 所有闸口能力通过单一 MCP Server 端点暴露给所有 AI Agent 平台（Claude Code、Codex、Trae 等），Agent 可以：

1. 通过 `goal_status` 查询当前目标
2. 通过 `extract_constraints` 提取约束候选
3. 通过 `confirm_constraint` / `reject_constraint` 管理约束
4. 通过 `expand_constraint` 调用 Gate 1.5 语义扩展
5. 通过 `gate2_check` / `list_rules` / `add_rule` 维护 Gate 2 规则
6. 通过 `sync_gate2` 把 Gate 1 约束同步成 Gate 2 动态规则
7. 通过 `drift_check` 调用 Gate 3 三档漂移检测
8. 通过 `overview` 一站式概览所有闸口状态

## 工具清单（15 个）

### Goal 管理（3）

| Tool | 说明 |
|------|------|
| `goal_status` | 查询当前已确认目标 |
| `goal_propose` | Agent 提议新目标（不可自行 confirm） |
| `goal_confirm` | 用户执行的目标确认（Agent 禁止）|

### Gate 1 约束管理（4）

| Tool | 说明 |
|------|------|
| `extract_constraints` | 从文本提取候选约束 |
| `list_constraints` | 列出 confirmed / rejected / pending |
| `confirm_constraint` | 用户确认约束（自动同步 Gate 2） |
| `reject_constraint` | 用户拒绝约束（删除 confirmed 记录） |

### Gate 1.5 语义扩展（1）

| Tool | 说明 |
|------|------|
| `expand_constraint` | 把约束文本扩展为多个同义词变体 |

### Gate 2 规则引擎（4）

| Tool | 说明 |
|------|------|
| `gate2_check` | 检查工具调用是否触发隐私/规则破坏 |
| `list_rules` | 列出所有规则（静态 + 动态）|
| `add_rule` | 动态添加规则 |
| `sync_gate2` | 把 Gate 1 约束同步成 Gate 2 动态规则 |

### Gate 3 漂移检测（2）

| Tool | 说明 |
|------|------|
| `drift_check` | 三档判定（aligned/ambiguous/drift） |
| `drift_review_plan` | drift_check 的别名（向后兼容）|

### 跨闸口辅助（1）

| Tool | 说明 |
|------|------|
| `overview` | 一站式概览：目标 + 约束统计 + Gate 2 + 决策 |

## 启动方式

### Stdio（推荐用于 IDE 集成）

```bash
python -m focusloop_mcp_server
```

### 平台接入配置

**Claude Code / Codex**: `.mcp.json`
```json
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
```

**Trae**: `.trae/mcp.json`
```json
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
```

**使用统一适配器生成**：
```bash
python -m gate2.multi_agent_code install claude_code --target .
python -m gate2.multi_agent_code install trae --target .
```

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `FOCUSLOOP_DB` | `.focusloop/state.sqlite3` | SQLite 数据库路径 |
| `FOCUSLOOP_PROJECT` | `focusloop-v1` | 项目标识（同一 DB 下多项目隔离）|
| `FOCUSLOOP_RULES` | `gate2/rules.json` | Gate 2 规则文件 |

## 关键设计点

### 1. Agent 不能自我确认（关键安全约束）

`goal_confirm` 和 `confirm_constraint` 必须由用户调用。Agent 在 `goal_propose` 后只能返回"hint"提示用户执行。

### 2. Gate 1 → Gate 2 自动联动

`confirm_constraint` 调用后会自动 `sync_from_store()`，把新约束生成 Gate 2 动态规则。

### 3. Gate 1.5 语义扩展内嵌

`expand_constraint` 暴露 ConstraintExpander，可被外部 Agent 用来理解 Gate 2 规则的语义覆盖范围。

### 4. 错误优雅降级

每个工具函数都有 try/except 返回详细错误（含 traceback），不阻塞其他调用。

## 验证测试

`tests/test_mcp_server.py` 通过 stdio JSON-RPC 完整测试：

```
1. tools/list → 15 个工具全部注册
2. overview (无目标) → goal=null, 6 静态规则
3. goal_propose → version=1
4. goal_confirm → status=confirmed
5. extract_constraints → 2 candidates (high confidence)
6. confirm_constraint × 2 → 自动同步 Gate 2
7. list_rules → 6 静态 + 2 动态（Gate 1.5 semantic）
8. gate2_check × 3：
   - "调用 第三方接口" → block (dyn-c_auto_002, semantic match)
   - "pip install requests" → block (g2-003, static rule)
   - "ls -la /tmp/" → passed
9. drift_check × 3：
   - 完全在范围 → aligned (1.0)
   - 无关内容 → drift (0.0)
   - Gate2 演进 → aligned (1.0)
10. overview (最终) → goal v1 + 2 confirmed + 6/2 rules + 1 decision
```

## 与旧 server 的差异

| 项 | 旧 `gate2/mcp_server.py` | 新 `focusloop_mcp_server.py` |
|----|-------------------------|----------------------------|
| 工具数 | 4（仅 Gate 2）| 15（所有闸口）|
| 目标管理 | ✓（只读）| ✓（完整 propose+confirm）|
| Gate 1 | ✗ | ✓ |
| Gate 1.5 | ✗ | ✓ |
| Gate 2 | ✓ | ✓（增强，含 dynamic rules） |
| Gate 3 | ✗ | ✓ |
| 错误处理 | 通用 | 详细（含 traceback）|

**旧 server 保留**：`gate2/mcp_server.py` 仍可用（向后兼容），但新代码应使用统一 server。

## 下一步

1. **HTTP/SSE 传输**：当前仅 stdio，未来支持 streamable HTTP 用于远程访问
2. **权限分层**：goal_confirm 等敏感操作考虑 OAuth/token 校验
3. **批量 API**：增加 batch_drift_check 等批量接口
4. **多项目隔离**：当前用 FOCUSLOOP_PROJECT 区分，未来可用 path-based isolation
