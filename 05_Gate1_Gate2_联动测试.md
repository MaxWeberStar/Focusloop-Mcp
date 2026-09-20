# Gate 1 + Gate 2 联动测试记录

**日期**：2026-09-20  
**状态**：✅ 通过

## 测试目标

验证用户通过 Gate 1 确认的约束能否自动转换为 Gate 2 动态规则，并在工具调用时触发拦截。

## 联动链路

```
[用户消息] 
    ↓
[Hook 提取] → constraint:c_auto_001 (候选)
    ↓
[用户确认] (交互式 review-constraints 或 confirm-constraint)
    ↓
[Store 存储] → confirmed_constraint:c_auto_001
    ↓
[Gate2Checker.sync_from_store()]
    ↓
[动态规则] → dyn-c_auto_001 (pattern=.*约束文本.*)
    ↓
[工具调用] → Gate 2 check → 命中 → block/log
```

## 核心实现

### 1. `gate2/checker.py` 新增

| 方法 | 作用 |
|------|------|
| `__init__(rules_path, store=None)` | 新增 store 参数 |
| `sync_from_store()` | 从 Store 读取 confirmed_constraint，生成动态规则 |
| `_build_dynamic_rule(cid, payload)` | 单条 constraint → 动态规则（默认 `(?i).*text.*` 模式） |
| `_all_rules()` | 静态 + 动态规则合并迭代 |

### 2. `focusloop.py` 新增 CLI

| 命令 | 作用 |
|------|------|
| `sync-gate2` | 把所有 confirmed constraints 同步为 Gate 2 动态规则 |
| `sync-gate2 --list-confirmed` | 列出可同步的 confirmed 约束 |
| `sync-gate2 --show` | 显示当前已加载的动态规则 |

### 3. Hook 自动同步

`hook` 子命令初始化 Gate2Checker 时自动调用 `sync_from_store()`，无需手动触发。

## 测试用例

### 测试 1：基本提取 → 确认 → sync

```bash
# 1. 提取候选
python3 focusloop.py --db /tmp/test.sqlite3 extract-constraints \
  --text "禁止使用第三方API"

# 2. 确认候选
python3 focusloop.py --db /tmp/test.sqlite3 confirm-constraint \
  --id c_auto_001 --text "使用第三方API" --source 用户确认 --confidence high

# 3. 同步到 Gate 2
python3 focusloop.py --db /tmp/test.sqlite3 sync-gate2
# 输出: {"synced_dynamic_rules": 1, "dynamic_rules": [{"id": "dyn-c_auto_001", ...}]}
```

### 测试 2：Gate 2 检查触发动态规则

```python
checker = Gate2Checker('gate2/rules.json', store=store)
checker.sync_from_store()

# 触发
result = checker.check('Bash', {'command': 'curl 调用外部API 抓数据'})
assert result.rule_id == 'dyn-c_auto_001'
assert result.constraint_ref == 'c_auto_001'
```

### 测试 3：约束被拒绝后不进动态规则

```bash
python3 focusloop.py reject-constraint --id c_auto_002 --reason 测试 --source 用户确认
# c_auto_002 不再出现在 sync-gate2 --list-confirmed
```

## 实际验证结果

| 约束类型 | 提取 | 确认 | 同步 | Gate 2 触发 |
|----------|------|------|------|-------------|
| `禁止使用第三方API` | ✅ c_auto_001 | ✅ high | ✅ dyn-c_auto_001 | ✅ 命中 |
| `禁止上传本地文件到云端` | ✅ c_auto_002 | ✅ high | ✅ dyn-c_auto_002 | ✅ 命中 |
| `不能直接读取项目以外的文件` | ✅ c_auto_003 | ✅ medium | ✅ dyn-c_auto_003 | ✅ 命中 |
| `上下文是测试`（拒绝）| ✅ c_auto_004 | ❌ rejected | ❌ 不生成规则 | ✅ 不触发 |

## 已知限制

### 1. 中文文本匹配的局限性

当前动态规则用 `(?i).*<约束文本>.*` 作为模式，**只能匹配包含约束原文的命令**。

例如：
- 约束文本：`使用第三方API`（中文）
- 匹配命令：`调用第三方API 获取数据` ✅
- 不匹配命令：`curl https://api.example.com` ❌（实际是同语义但用了不同表述）

**改进方向**：在 `_build_dynamic_rule` 中加入语义扩展：
- 提取约束中的关键动词（调用、使用、上传）和对象（API、文件）
- 生成 `动词 + .* + 对象` 的宽松模式
- 或调用语义层（Gate 1.5）做扩展

### 2. 重复约束去重

如果用户多次确认相同文本的约束，会生成多条 id 不同但 pattern 相同的规则。当前没有去重逻辑。

### 3. 约束撤销

当前没有"撤销已确认约束"的命令。如果用户想撤回，需要手动 `reject-constraint`（语义不准确），或删除 Store 记录。

## 下一步

1. **Gate 1.5 语义层**：扩展约束文本到多个变体（用 Claude 做语义扩展）
2. **Gate 2 增强**：支持子串 + 模糊匹配
3. **约束生命周期**：添加 revoke-confirmed-constraint 命令
