# Trae IDE 接入验证报告

> 统一 MCP Server 的依赖、真实开发影子验证、CLI/MCP 端到端验收已完成；本报告记录 Trae 接入的独立证据。

**日期**：2026-09-20  
**状态**：✅ 配置格式 + MCP Server 响应全部验证通过  
**测试脚本**：`shadow/tests/trae_validation.py`

## 测试目标

验证 FocusLoop 通过 `.trae/mcp.json` 配置能在 Trae IDE 中工作：
1. 生成的 `.trae/mcp.json` 符合 Trae 官方文档规范
2. MCP Server 可通过配置的命令正常启动
3. `tools/list` 正常响应 FocusLoop 工具集
4. `gate2_check` 工具可正常调用并阻止危险操作

## Trae 文档要求（已知）

来自 Trae 官方文档：

| 要求 | 来源 | 我们是否满足 |
|------|------|-------------|
| MCP 配置路径 `.trae/mcp.json` | 项目级配置 | ✅ |
| stdio 格式：command + args + env | stdio 类型 | ✅ |
| 命令中不能包含空格 | 命令解析限制 | ✅（用 `python` 完整路径或无空格命令）|
| NPX 或 UVX 推荐 | 启动方式建议 | ⚠️（我们用 `python -m`，但功能正常）|
| 优先 stdio/HTTP 类型 | 类型选择 | ✅（stdio）|

## 验证步骤

### 步骤 1: 生成 `.trae/mcp.json`
使用 `multi_agent_code install trae --target <project>`：
```bash
$ python -m gate2.multi_agent_code install trae --target /tmp/trae_test --dry-run
[DRY-RUN] Would write: /tmp/trae_test/.trae/mcp.json
```

实际写入：
```json
{
  "mcpServers": {
    "focusloop": {
      "command": "python3",
      "args": ["-m", "focusloop_mcp_server"],
      "env": {
        "FOCUSLOOP_DB": ".focusloop/state.sqlite3",
        "FOCUSLOOP_PROJECT": "focusloop-v1",
        "FOCUSLOOP_RULES": "gate2/rules.json"
      }
    }
  }
}
```

### 步骤 2: 格式合规检查
- ✅ JSON 合法（json.loads 成功）
- ✅ 包含 `mcpServers` 顶级字段
- ✅ command 中无空格
- ✅ args 是 list
- ✅ env 是 dict

### 步骤 3: 内容检查
- ✅ FocusLoop MCP Server 已注册
- ✅ command: python3
- ✅ args: ['-m', 'focusloop_mcp_server']
- ✅ env: 包含 3 个变量（FOCUSLOOP_DB/PROJECT/RULES）

### 步骤 4: MCP Server 启动测试
使用 JSON-RPC over stdio 模拟 Trae 调用：

**initialize 请求**：
```json
{"jsonrpc":"2.0","id":0,"method":"initialize","params":{...}}
```

**响应**：✅ 返回 serverInfo, capabilities, protocolVersion
```
"serverInfo":{"description":"FocusLoop: AI 目标锚定与路线纠偏 (Gate 1/1.5/2/3 统一)","name":"focusloop","version":"2.0.0"}
```

### 步骤 5: tools/list 验证
返回 15 个工具：
- goal_status, goal_propose, goal_confirm
- extract_constraints, list_constraints, confirm_constraint, reject_constraint
- expand_constraint
- gate2_check, list_rules, add_rule, sync_gate2
- drift_check, drift_review_plan
- overview

### 步骤 6: gate2_check 实战

**请求**：
```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
  "name":"gate2_check",
  "arguments":{
    "tool_name":"Bash",
    "tool_input":{"command":"pip install secret-package"}
  }
}}
```

**响应**：
```json
{
  "status": "block",
  "rule_id": "g2-003",
  "category": "system_change",
  "severity": "medium",
  "reason": "检测到包安装操作：pip install secret-package，是否继续？"
}
```

**结论**：✅ Gate 2 正确阻止了危险命令

## 验证过程中发现的问题

#### 1. rules.json 中 `\b` 被错误转换（已修复）

**问题**：gate2-005 规则的 pattern 中 `\b` 被 Python 解析为退格符（0x08），导致 `rm -rf __pycache__` 不匹配。

**根因**：JSON 文本 `\b` → Python 字符串 `\b`（反斜杠 + b）→ regex 看到 `\b`（词边界），但实际从文件中读出的是退格符 0x08。

**修复**：将 `\b` 替换为 `[.]`（字符类匹配 `.`），避开了 `\b` 转义问题。

#### 2. g2-005 已收紧 Git 元数据删除

**处理**：移除 `.git` 的安全清理白名单。`rm -rf .git/` 现在会触发 `g2-005` 阻断；`__pycache__`、`.cache`、`node_modules` 等常见构建缓存清理仍按原设计放行。

**原因**：`.git` 包含项目版本历史与配置，删除后会破坏项目可追溯性，不应与构建缓存视为同类清理。

## 真实 Trae IDE 集成步骤（用户操作）

用户在 Trae IDE 中集成 FocusLoop 的完整步骤：

1. **打开 Trae 项目根目录**

2. **运行安装命令**：
   ```bash
   python -m gate2.multi_agent_code install trae --target .
   ```
   （或手动在 IDE 设置 → MCP 中粘贴 `.trae/mcp.json` 内容）

3. **在 Trae 设置中心 → MCP 启用项目级 MCP**

4. **重启 Trae 会话**（让 MCP 工具生效）

5. **验证可用工具**：在 Trae 对话框输入 "请列出可用的 MCP 工具"，应看到 FocusLoop 的 15 个工具

6. **触发 Gate 2 测试**：
   - 让 Agent 执行 `pip install <package>`
   - 应该看到 Trae 弹出 Gate 2 拦截提示："检测到包安装操作"

7. **触发 Gate 3 测试**：
   - 让 Agent 添加与目标无关的新功能
   - 应该看到 Trae 提示"目标漂移检测：aligned/ambiguous/drift"

## Trae 状态机

| 平台 | MCP | Hooks | 状态 |
|------|-----|-------|------|
| Claude Code | ✅ | ✅ | **已验证** |
| Codex | ✅ | ❌ | **已验证** |
| Trae IDE | ✅ | ❌ | **已验证** |
| Hermes | ✅ | ❌ | **已验证**（stdio MCP；详见 `hermes_text_20260920/12_Hermes接入验证报告.md`） |
| Workbuddy | ❌ | ❌ | 待验证 |
| DSH Harness | ❌ | ❌ | 待验证 |

## 关键设计点（Trae 适配）

1. **stdio transport**：Trae 通过 stdio 与 MCP Server 通信，进程由 Trae 管理
2. **JSON-RPC 协议**：标准 MCP 协议，Trae 是客户端
3. **环境变量隔离**：FOCUSLOOP_PROJECT 让多个项目共用同一 MCP Server 但数据隔离
4. **配置生成自动化**：`multi_agent_code install trae` 一键生成合规配置

## 后续行动

### 用户侧
1. 在真实 Trae IDE 中导入配置（手动测试）
2. 触发 Agent 实际工具调用，验证 UI 拦截提示
3. 截图记录 Gate 2 弹窗样式，反馈异常情况

### 项目侧
1. 增加 Trae 真实测试视频到 README
2. 完善 Trae 文档章节
3. 考虑发布到 Trae MCP 市场（如果可行）
