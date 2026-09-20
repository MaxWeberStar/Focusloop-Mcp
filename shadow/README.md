# FocusLoop 状态与影子模式原型

本阶段实现版本化目标、决策与观察记录、结构化影子审查。所有运行命令在本目录执行。与 claude_hook_probe 独立；没有复用其文件门禁。

## 调用方式与数据

运行时仅用 Python 标准库及已安装的 Claude Code。SQLite 默认保存在 .focusloop/state.sqlite3，以 --project 隔离项目。uv 管理开发环境，pytest 运行测试。

语义审查调用 `claude --safe-mode -p --tools "" --strict-mcp-config --no-session-persistence`，在临时工作目录运行；60 秒超时。复用已有登录、模型与服务配置，不新建凭证；摘要会发送到该配置指向的服务并消耗额度，不是本地离线推理。未知、超时及错误格式均记录 unknown。禁用自定义 hooks 与工具，避免递归审查。

## 使用步骤

1. 运行 `uv run pytest -q`。
2. 提议目标：`uv run python focusloop.py propose example_goal.json --source "用户需求记录"`。
3. 用户核对文件后，在自己的终端执行 `uv run python focusloop.py confirm 1 --expected 0 --source "用户明确确认目标 v1"`。数字以命令实际返回为准。Agent 不得自行为真实项目批准；合成测试中的批准仅为测试数据。命令来源是约定，不是身份认证或防篡改边界。
4. 记录用户决定：`uv run python focusloop.py decide d1 "独立工作台延后到后续版本" --expected 1 --source "用户明确决定"`。替代旧决定用新的 ID 加 `--supersedes d1`。决策不隐式改写目标；目标变化需要新版本。
5. 提交精简观察：`uv run python focusloop.py observe sample-1 "准备追加开发独立工作台"`。
6. 审查：`uv run python focusloop.py review sample-1`。
7. 查看状态、决定和检查结果：`uv run python focusloop.py status`。

事件 ID 不可复用于不同内容。同一观察和审查器的结果复用，不重复消耗模型调用；失败结果也保留。重新尝试需明确创建新的观察 ID。旧观察按原目标版本存档，目标已更新时不拿旧观察评判新目标。

## 自动事件采集

从本 shadow 目录启动 `claude`，用 `/hooks` 核对本目录配置。自动收集三种事件的类型、会话 ID、工具名和工具调用 ID，不保存完整提示、命令或文件内容，不调用审查模型，不返回 allow/deny。

不自带稳定事件 ID 的用户提示只保证逐次到达记录；不能断言跨重试精准去重。工具事件用 session、event、tool_use_id 识别重放。

自动采集的元数据没有充分语义，不能直接推断三类偏移。当前通过 observe 提交选定摘要后显式 review；这是半自动影子原型，不是全自动监控。下一阶段如需自动构造摘要，应单独验证内容选择、隐私范围与失真。

## 可复现验证

`uv run python evaluate.py` 查看七个合成案例。

`uv run python evaluate.py --live` 调用现有 Claude 服务评判七个案例：三类偏移、正常排障、必要探索、授权改目标和信息不足。每个测试用独立临时数据库。此为冒烟测试，不能作为真实用户准确率或与基线比较的结果。

影子判定为 aligned、suspected_drift、unknown；偏移记录必须同时引用目标/决定及观察的原文片段。程序核对引用存在，不能证明模型推断正确。正常结果不构成任何工具授权。
