# Gate 3 语义层 v2 设计

**真实开发回归：✅ 已完成**

使用当前 FocusLoop/Trae 开发阶段记录的 7 条人工标注场景运行
`shadow/tests/gate3_real_data_validation.py`，7/7 与预期一致：4 aligned、1
ambiguous、2 drift，并通过 0.70/0.46/0.10 三个阈值边界回归。当前阈值为 high=0.65、low=0.30；该结果是工程回归证据，
不宣称已经完成大样本统计效果评估。

**日期**：2026-09-20  
**状态**：✅ 实现完成  
**解决问题**：规则层 token/phrase 匹配对措辞敏感，三档判定替代二元判断。

## v1 → v2 改进点

| 维度 | v1 | v2 |
|------|-----|-----|
| 判定档位 | 二元（drift / not） | **三档**（aligned / ambiguous / drift） |
| 公式 | `phrase_cov * 0.6 + token_cov * 0.4` | `sem_score * 0.7 + literal_score * 0.3` |
| 语义感知 | 无 | **集成 Gate 1.5 ConstraintExpander** |
| 阈值 | 单 0.50 | **high (0.65) / low (0.30) 双阈值** |
| 演进检测 | 字符串子串 | **Gate 1.5 语义匹配 + dominant 比率** |
| 置信度 | 随机 | **基于 literal vs semantic 差距** |
| LLM 兜底 | 不可用时崩溃 | **优雅降级到规则层** |
| 可解释性 | 仅 overlap_score | **explanation + 详细 scores + method** |

## 核心数据流

```
check_gate3(goal, current_ctx)
    ↓
1. 计算演进标记: evolution_tags = match against KNOWN_EVOLUTION_FUNCTIONS
    ↓
2. 双轨计算覆盖度:
   literal_score   = compute_overlap(orig_tokens, cur_tokens)
   semantic_score  = ConstraintExpander.expand(orig + cur) → 重叠
    ↓
3. 综合分:
   pure_evolution        → combined = 1.0
   evolution_dominant    → combined = max(score, low_threshold + 0.01)
   其他                  → combined = semantic*0.7 + literal*0.3
    ↓
4. 三档判定:
   combined ≥ high (0.65)  → aligned
   combined < low  (0.30)  → drift
   中间区间                 → ambiguous
    ↓
5. 可选 LLM 兜底 (仅在 ambiguous 或 confidence=low 时调用)
    ↓
6. 生成 DriftReport（含 verdict / confidence / explanation）
```

## 三档判定语义

| verdict | 含义 | 处理建议 |
|---------|------|----------|
| **aligned** | 高覆盖 / 纯演进 / 演进主导 | 继续（不提示）|
| **ambiguous** | 灰区（0.30-0.65）| 提示用户确认（gate 1 触发）|
| **drift** | 低覆盖且非演进 | 阻断 + 显示原始目标 vs 当前内容 |

## 关键函数

### `literal_coverage(orig_texts, cur_texts)`
保留 v1 公式作为对照基线（phrase + token bigrams）。

### `semantic_coverage(orig_texts, cur_texts, expander)`
集成 Gate 1.5 的 `ConstraintExpander`：
1. 对 orig 和 cur 都做语义扩展
2. 计算扩展后的 token 集合重叠
3. 返回扩展后的覆盖率

### `_three_tier_verdict(score, evo_exempt, high, low)`
返回 `(verdict, drift_detected)`：
- evo_exempt=True → aligned（不论覆盖率）
- score >= high → aligned
- score < low → drift
- 中间 → ambiguous（默认按 drift 提示但建议用户确认）

### `_compute_confidence(literal, semantic)`
基于两轨差距：
- gap < 0.10 → high
- gap < 0.25 → medium
- gap ≥ 0.25 → low（需要语义兜底）

### `_llm_semantic_judge(...)`
可选 LLM 兜底：
- 仅在 `semantic=True` AND (`verdict == ambiguous` OR `confidence == low`) 时调用
- 调用失败返回 None，不影响主流程
- 成功时用 LLM verdict 修正最终判断

## 验证测试

| 场景 | ctx 示例 | 期望 | 结果 |
|------|----------|------|------|
| 字面完全对齐 | `['规则层','语义层','原型演示']` | aligned | ✅ |
| 纯 Gate2/MCP 演进 | `['Gate2 MCP Server']` | aligned | ✅ (pure_evolution) |
| Gate1.5 主导 | `['Gate1.5 语义扩展器','同义词词典生成']` | aligned | ✅ (evolution_dominant) |
| 部分对齐+辅助工作 | `['规则层漂移检测','单元测试补充','代码整理']` | ambiguous | ✅ (combined=0.46) |
| 完全无关 | `['PRD草案','市场报告']` | drift | ✅ |
| 完全不相关话题 | `['写一篇养猫的文章']` | drift | ✅ |

## CLI 输出示例

```bash
$ python3 focusloop.py drift --context "Gate2 MCP Server" "影子模式原型"
{
  "verdict": "aligned",
  "drift_detected": false,
  "overlap_score": 1.0,
  "literal_score": 0.067,
  "semantic_score": 0.067,
  "method": "pure_evolution",
  "confidence": "medium",
  "explanation": "当前工作完全由已知必要演进构成（2 条），不偏离原始目标",
  "evolution_tags": ["Gate2 MCP Server", "影子模式原型"]
}
```

```bash
$ python3 focusloop.py review-plan --context "PRD草案文档" "市场调研报告"
{
  "verdict": "drift",
  "drift_detected": true,
  "overlap_score": 0.0,
  "literal_score": 0.0,
  "semantic_score": 0.0,
  "method": "hybrid",
  "confidence": "high",
  "explanation": "语义覆盖率仅 0%，与原始目标差异较大"
}
```

## 已知局限

### 1. 知识库覆盖

`KNOWN_EVOLUTION_FUNCTIONS` 静态枚举已知演进项。新功能需手动加入（可由 LLM 自动扩展）。

### 2. 语义扩展稀释

`Gate1.5 ConstraintExpander` 把所有 token 扩展为多种变体，对小数据集可能稀释覆盖率（噪声 token 增多）。

**缓解**：semantic_score 仍用 token 集合重叠，受扩展噪声影响有限。

### 3. LLM 依赖

`_llm_semantic_judge` 需要 `claude` CLI 可用。失败时 fallback 到规则层 verdict。

## 下一步

1. **自动扩展 KNOWN_EVOLUTION_FUNCTIONS**：基于已确认的 Gate 1 约束自动学习
2. **方向语义**：解决 "禁止" vs "必须" 的区分（目前 pure_evolution 不区分方向）
3. **多模态扩展**：支持更多输入（不只是文本 list）
4. **MCP Server 暴露**：把 Gate 3 检查通过 MCP 工具暴露给外部 Agent
