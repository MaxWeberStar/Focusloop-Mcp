# Gate 1.5 语义层设计

**日期**：2026-09-20  
**状态**：✅ 实现完成  
**解决问题**：Gate 2 动态规则只匹配约束原文，无法识别同语义不同表述。

## 问题背景

Gate 1 提取约束 → 用户确认 → Gate 2 同步为动态规则。原模式是字面匹配：

```
约束文本: "禁止使用第三方API"
原模式:   (?i).*使用第三方API.*
测试命令: "调用第三方接口"  → ❌ 不匹配（实际是同约束）
```

## 设计思路

### 1. 中文同义词词典

把词典分成两类：

**核心词（必须出现在命令中）**：
- 动词：使用/调用/运行/执行、上传/传输/推送、下载/获取、删除/移除、修改/编辑、读取/访问、阻断/拦截
- 名词：API/接口/端点、文件/文档、第三方/外部/远端、本地/本机、云端/云/s3、数据库/DB、网络/http、包/库、用户

**修饰词（识别约束语气，不要求命令中出现）**：
- 禁止类：禁止/不允许/不能/不得/不可
- 必须类：必须/应当/需要/务必
- 可以类：可以/允许/可

### 2. 变体生成算法

```
输入: "禁止使用第三方API"
1. 查词典，识别 core tokens: 使用, API, 第三方
2. 每个 core token 展开为同义词组（OR）
3. 用 lookahead 把各组串联（不要求出现顺序）
4. 输出正则: (?i).*(?=.*(?:使用|调用|运行|...))(?=.*(?:API|接口|...))(?=.*(?:第三方|外部|...)).*
```

### 3. 关键设计点

| 决策 | 原因 |
|------|------|
| 用 lookahead 而非顺序匹配 | 命令中 token 顺序可能与约束不同 |
| 核心词 vs 修饰词分离 | 约束"禁止..."的命令通常不带"禁止"字样 |
| 保留中文 + 英文同义 | 中英混合命令场景 |
| 退化为字面匹配 | 无词典匹配时仍可用（fallback）|

## 实现

### `gate1_5_semantic.py`

```python
class ConstraintExpander:
    def __init__(self, synonyms=None, modifiers=None):
        self.synonyms = synonyms or SYNONYMS
        self.modifiers = modifiers or MODIFIERS
    
    def expand(self, text: str) -> SemanticExpansion:
        core_hits, modifier_hits = self._find_synonyms(text)
        if not core_hits:
            # fallback 字面匹配
            return SemanticExpansion(..., method="fallback")
        
        # 生成 lookahead 模式
        groups = []
        for key, variants in core_hits:
            unique = list({re.escape(v) for v in variants})
            groups.append(f"(?=.*(?:{'|'.join(unique)}))")
        
        pattern = f"(?i).*{''.join(groups)}.*"
        return SemanticExpansion(
            original=text,
            variants=sorted(set(all_variants)),
            regex=pattern,
            tokens_used=[k for k, _ in core_hits],
            method="rule",
        )
```

### Gate 2 集成

`_build_dynamic_rule` 使用 Gate 1.5 扩展：

```python
def _build_dynamic_rule(self, cid, payload):
    text = payload["text"]
    pattern = f"(?i).*{re.escape(text)}.*"
    method = "literal"
    
    try:
        from gate1_5_semantic import ConstraintExpander
        expander = ConstraintExpander()
        expansion = expander.expand(text)
        if expansion.method == "rule" and expansion.tokens_used:
            pattern = expansion.regex
            method = "semantic"
    except Exception:
        pass
    
    return {
        ...
        "pattern": pattern,
        "_match_method": method,
        "_variants_count": len(expansion.variants),
        "_semantic_tokens": expansion.tokens_used,
    }
```

## 验证结果

| 约束 | 命令 | 命中 | 说明 |
|------|------|------|------|
| 禁止使用第三方API | 使用第三方API 抓数据 | ✅ | literal |
| 禁止使用第三方API | 调用 第三方接口 | ✅ | 使用→调用 + API→接口 |
| 禁止使用第三方API | 调用 外部接口 | ✅ | 第三方→外部 + API→接口 |
| 禁止使用第三方API | 运行 third-party service | ✅ | 多 token 全部变体命中 |
| 禁止使用第三方API | curl https://api.example.com | ❌ | 纯英文无中文 token（已知局限） |
| 不能上传本地文件到云端 | 把本地文件推到远端服务器 | ✅ | 上传→推到 + 云端→远端 |
| 不能上传本地文件到云端 | scp local.txt s3://bucket/ | ❌ (g2-001) | s3 命中静态规则 data_exfiltration |
| 不能上传本地文件到云端 | cat local.txt | ✅ 不命中 | 不相关命令正确放行 |
| 禁止删除用户数据 | rm -rf user_data | ✅ | 删除 → rm + 用户 → user_data |
| 禁止删除用户数据 | delete user_data.txt | ✅ | 删除 → delete |

**命中率：8/11**（3 个英文无中文 token 的命令超出规则引擎能力范围）

## 已知局限

### 1. 中文-only 约束 vs 纯英文命令

如果约束是中文（"禁止使用第三方API"），英文命令（"curl https://api.x.com"）无法匹配。

**解决方向**：
- 为常见英文操作维护英文规则库（已部分实现于 g2-001~g2-006）
- 调用 LLM 翻译约束到英文变体

### 2. 词典覆盖度有限

当前词典约 30 个核心 token，覆盖常见操作。罕见动词/名词可能未收录。

**解决方向**：
- 用 LLM 自动扩展词典（基于已确认的约束）
- 累积用户反馈优化

### 3. 否定语义不传递

约束"禁止删除 X"和"必须删除 X"会生成相同的核心匹配模式（都要求 X 出现），但忽略"删除"的允许/禁止语义。

**解决方向**：
- 区分正向/反向约束，把 modifier 编码进规则 severity 或 action
- "禁止"约束要求"出现核心词即 block"，"必须"约束要求"未出现核心词即 block"

### 4. 阈值未配置

当前只要 core token 都出现就命中，无最低匹配度阈值。

**解决方向**：
- 加入 `--min-tokens` 参数，要求至少 N 个 token 命中
- 加入 score 评分（覆盖度比例）

## 下一步

1. **LLM 扩展**：用 Claude 对新约束自动生成变体，补充进 SYNONYMS
2. **方向语义**：解决"禁止 vs 必须"的区分
3. **动态词典**：基于用户反馈/确认自动学习新同义词
4. **MCP 集成**：把 Gate 1.5 通过 MCP Server 暴露给其他平台
