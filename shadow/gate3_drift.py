"""
Gate 3 漂移检测 v2：集成 Gate 1.5 语义扩展，三档判定（aligned/ambiguous/drift）。

核心改进：
1. 集成 ConstraintExpander（Gate 1.5）做语义感知覆盖度
2. 三档判定替代二元（aligned/ambiguous/drift）
3. 置信度基于覆盖率差距计算（高/中/低）
4. 可选 LLM 语义兜底，失败时优雅降级到规则层
5. 演进检测使用语义匹配而非字符串子串
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any


# ── 必要演进知识库 ──────────────────────────────────────
# 当上下文完全由这些功能构成时，视为 100% 在原始范围内
KNOWN_EVOLUTION_FUNCTIONS: set[str] = {
    # Gate 1.x 约束管理
    "gate1", "gate1_extractor", "constraint extraction", "约束提取",
    "gate1.5", "semantic expander", "同义词扩展", "语义扩展",
    # Gate 2 隐私规则
    "gate2", "gate2checker", "gate2 checker", "规则引擎",
    "privacy", "rules.json", "rules check",
    # Gate 3 漂移检测
    "gate3", "drift detection", "漂移检测",
    # MCP 跨平台
    "mcp", "mcp server", "model context protocol",
    "multi agent", "multi_agent_code", "多平台适配",
    # Shadow mode 模式
    "shadow mode", "shadow_mode", "影子模式",
}


STOP_EN = {
    "the","a","an","is","are","was","were","be","been",
    "have","has","had","do","does","did","will","would",
    "could","should","may","might","can","to","of","in",
    "for","on","with","at","by","from","as","into",
    "that","this","these","those","it","its",
    "and","or","but","if","then","else","when",
    "up","out","no","so","just","only","also","very",
    "more","most","some","any","all","each","every",
    "both","few","many","much","such","other","another",
    "not","none","one","two","three","four","five",
    "first","second","third","new","old","same","different",
}


# ── 覆盖率公式 ──────────────────────────────────────────

def _tokenize(text: str) -> set[str]:
    """中文 bigram + 英文 word tokenization。"""
    tokens: set[str] = set()
    tl = re.sub(r'[,，、。.！!?"\':;\\-\\s]+', ' ', text.lower())
    # 中文 bigrams 2-4 char
    for seq in re.findall(r'[一-鿿]+', tl):
        for n in (2, 3, 4):
            for i in range(len(seq) - n + 1):
                tokens.add(seq[i:i + n])
    # 英文 words
    for w in re.findall(r'[a-z0-9]{2,}', tl):
        if w not in STOP_EN and len(w) > 1:
            tokens.add(w)
    return tokens


def _phrase_extract(text: str) -> set[str]:
    """提取中文 bigram 和英文 2-3 gram phrase。"""
    phrases: set[str] = set()
    tl = text.lower()
    for seq in re.findall(r'[一-鿿]+', tl):
        for n in (2, 3, 4):
            for i in range(len(seq) - n + 1):
                phrases.add(seq[i:i + n])
    words = re.findall(r'[a-z0-9]+', tl)
    for n in (2, 3):
        for i in range(len(words) - n + 1):
            phrase = ' '.join(words[i:i + n])
            if len(phrase) > 4:
                phrases.add(phrase)
    return phrases


def literal_coverage(orig_texts: list[str], cur_texts: list[str]) -> tuple[float, dict]:
    """纯字面覆盖率（保留 v1 公式做对照基线）。"""
    if not orig_texts or not cur_texts:
        return 0.0, {'method': 'literal'}
    ot: set[str] = set()
    op: set[str] = set()
    for t in orig_texts:
        ot |= _tokenize(t)
        op |= _phrase_extract(t)
    ct: set[str] = set()
    cp: set[str] = set()
    for t in cur_texts:
        ct |= _tokenize(t)
        cp |= _phrase_extract(t)
    if not ct:
        return 0.0, {'method': 'literal'}
    token_cov = len(ot & ct) / len(ct)
    phrase_cov = len(op & cp) / max(len(cp), 1)
    coverage = phrase_cov * 0.6 + token_cov * 0.4
    return round(coverage, 3), {
        'method': 'literal',
        'token_coverage': round(token_cov, 3),
        'phrase_coverage': round(phrase_cov, 3),
        'orig_token_cnt': len(ot),
        'cur_token_cnt': len(ct),
        'matched': len(ot & ct),
    }


def semantic_coverage(
    orig_texts: list[str],
    cur_texts: list[str],
    expander: Any | None = None,
) -> tuple[float, dict]:
    """Gate 1.5 增强的语义覆盖率。

    对原始目标和当前上下文都做语义扩展，比较扩展后的 token 集合重叠度。
    """
    if not orig_texts or not cur_texts:
        return 0.0, {'method': 'semantic'}

    if expander is None:
        try:
            from gate1_5_semantic import ConstraintExpander
            expander = ConstraintExpander()
        except ImportError:
            return literal_coverage(orig_texts, cur_texts)

    def _expand_to_tokens(texts: list[str]) -> set[str]:
        toks: set[str] = set()
        for t in texts:
            tlow = t.lower()
            toks |= _tokenize(tlow)
            try:
                expansion = expander.expand(t)
                # 把扩展的 variants 转成 tokens（按非字母数字切分）
                for v in expansion.variants:
                    toks |= _tokenize(v)
            except Exception:
                pass
        return toks

    ot = _expand_to_tokens(orig_texts)
    ct = _expand_to_tokens(cur_texts)
    if not ct:
        return 0.0, {'method': 'semantic'}
    overlap = len(ot & ct)
    coverage = overlap / len(ct)
    return round(coverage, 3), {
        'method': 'semantic',
        'orig_token_cnt': len(ot),
        'cur_token_cnt': len(ct),
        'matched': overlap,
        'expansion_used': True,
    }


# ── 三档判定系统 ────────────────────────────────────────

@dataclass
class DriftReport:
    """Gate 3 漂移检测报告。"""
    overlap_score: float                  # 综合覆盖率（0-1）
    literal_score: float                  # 字面覆盖率
    semantic_score: float                 # 语义覆盖率
    drift_pct: float                      # 偏离百分比
    drift_detected: bool                  # 是否判定为漂移
    verdict: str                          # aligned / ambiguous / drift
    confidence: str                       # high / medium / low
    method: str                           # literal / semantic / hybrid
    original_scope: list[str] = field(default_factory=list)
    current_scope: list[str] = field(default_factory=list)
    new_items: list[str] = field(default_factory=list)
    dropped_items: list[str] = field(default_factory=list)
    evolution_tags: list[str] = field(default_factory=list)
    raw_overlap_details: dict[str, Any] = field(default_factory=dict)
    semantic_verdict: str | None = None   # LLM 语义判断结果
    semantic_reasoning: str | None = None
    explanation: str = ""                 # 人类可读的判断说明

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def _detect_evolution_tags(current_ctx: list[str]) -> list[str]:
    """检测当前上下文中哪些是已知必要演进。"""
    tags: list[str] = []
    for item in current_ctx:
        ilower = item.lower()
        for ev in KNOWN_EVOLUTION_FUNCTIONS:
            if ev in ilower:
                tags.append(item)
                break
    return tags


def _is_pure_evolution(evolution_tags: list[str], current_ctx: list[str]) -> bool:
    """判断当前上下文是否完全由已知演进构成。"""
    return len(evolution_tags) == len(current_ctx) and len(current_ctx) > 0


def _is_evolution_dominant(evolution_tags: list[str], current_ctx: list[str], ratio: float = 0.5) -> bool:
    """判断已知演进项是否占主导（≥60%）。"""
    if not current_ctx:
        return False
    return len(evolution_tags) / len(current_ctx) >= ratio


def _compute_confidence(literal: float, semantic: float) -> str:
    """基于两个覆盖率差距计算置信度。

    - 差距小（< 0.10）→ high（两个指标一致）
    - 差距中（0.10-0.25）→ medium
    - 差距大（> 0.25）→ low（指标不一致，需要语义兜底）
    """
    gap = abs(literal - semantic)
    if gap < 0.10:
        return "high"
    elif gap < 0.25:
        return "medium"
    return "low"


def _three_tier_verdict(
    score: float,
    is_pure_evo: bool,
    high_threshold: float = 0.65,
    low_threshold: float = 0.30,
) -> tuple[str, bool]:
    """三档判定：
    - aligned (≥ high_threshold 或 pure_evo): 不算漂移
    - drift (< low_threshold): 漂移
    - ambiguous: 中间地带

    Returns: (verdict, drift_detected)
    """
    if is_pure_evo:
        return "aligned", False
    if score >= high_threshold:
        return "aligned", False
    if score < low_threshold:
        return "drift", True
    return "ambiguous", True  # 灰区，默认按 drift 提示但需用户确认


def _build_explanation(
    verdict: str,
    semantic_score: float,
    evolution_tags: list[str],
    new_items: list[str],
) -> str:
    """生成人类可读的判断说明。"""
    parts: list[str] = []
    if verdict == "aligned":
        if evolution_tags and len(evolution_tags) == len(new_items):
            parts.append(f"当前工作完全由已知必要演进构成（{len(evolution_tags)} 条），不偏离原始目标")
        else:
            parts.append(f"语义覆盖率 {semantic_score:.0%}，与原始目标高度对齐")
    elif verdict == "ambiguous":
        parts.append(f"语义覆盖率 {semantic_score:.0%}，处于灰区（0.30-0.65），建议用户确认")
        if evolution_tags:
            parts.append(f"包含 {len(evolution_tags)} 条已知演进")
    else:  # drift
        parts.append(f"语义覆盖率仅 {semantic_score:.0%}，与原始目标差异较大")
    return "；".join(parts)


# ── 语义兜底（LLM） ──────────────────────────────────────

def _llm_semantic_judge(
    orig_texts: list[str],
    cur_texts: list[str],
    score: float,
    verdict: str,
    model: str = "claude",
    timeout: int = 60,
) -> dict[str, str] | None:
    """调用 LLM 做最终语义判断，失败时返回 None。

    仅在 ambiguous 或 confidence=low 时调用。
    """
    orig_block = '\n'.join(f'- {t}' for t in orig_texts)
    cur_block = '\n'.join(f'- {t}' for t in cur_texts)
    prompt = f"""你是 FocusLoop 路线审查员。

## 原始目标
{orig_block}

## 当前实施内容
{cur_block}

## 量化指标
- 语义覆盖率: {score:.0%}
- 规则层判定: {verdict}

## 任务
判断当前实施内容是否偏离原始目标（范围扩大 vs 必要演进）。

输出 JSON（不要其他文字）：
{{"verdict":"aligned|ambiguous|drift","confidence":"high|medium|low","reasoning":"<一句话原因>","action":"continue|refocus|confirm_expansion"}}
"""
    cmd_args = [model, "--safe-mode", "-p", "--no-mcp", "--output-format", "json"]
    try:
        r = subprocess.run(
            cmd_args, input=prompt, capture_output=True, text=True,
            timeout=timeout, cwd=tempfile.gettempdir(),
        )
        if r.returncode != 0:
            return None
        result = json.loads(r.stdout)
        return result.get('structured_output') or result
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        return None


# ── 主入口 ──────────────────────────────────────────────

def check_gate3(
    goal: dict[str, Any],
    current_ctx: list[str],
    threshold: float = 0.50,            # 兼容旧参数（不再直接使用）
    semantic: bool = False,
    model: str | None = None,
    high_threshold: float = 0.65,
    low_threshold: float = 0.30,
) -> DriftReport:
    """Gate 3 漂移检测主入口（v2 语义增强版）。

    Args:
        goal: 目标 payload（含 objective/deliverables/constraints/non_goals）
        current_ctx: 当前实施内容列表
        threshold: 兼容旧参数（实际使用 high/low_threshold）
        semantic: 是否启用 LLM 语义兜底
        model: LLM 模型名（默认 "claude"）
        high_threshold: 覆盖率≥此值判定为 aligned
        low_threshold: 覆盖率<此值判定为 drift
    """
    orig_d = goal.get('deliverables', [])
    orig_da = goal.get('dev_activities', [])      # 典型开发活动
    orig_o = goal.get('objective', '')
    orig_c = goal.get('constraints', [])
    orig_ng = goal.get('non_goals', [])
    orig_texts = [t for t in [orig_o] + orig_d + orig_da + orig_c + orig_ng if t]

    evolution_tags = _detect_evolution_tags(current_ctx)
    pure_evo = _is_pure_evolution(evolution_tags, current_ctx)

    # 双轨计算
    lit_score, lit_details = literal_coverage(orig_texts, current_ctx)
    sem_score, sem_details = semantic_coverage(orig_texts, current_ctx)

    # 计算演进豁免（用于 verdict 计算）
    evo_dominant = _is_evolution_dominant(evolution_tags, current_ctx)
    evo_exempt = pure_evo or evo_dominant

    # 综合分计算
    if pure_evo:
        combined = 1.0
        method = "pure_evolution"
    elif evo_dominant and (sem_score < low_threshold):
        # 演进主导但语义覆盖低：提升到略高于低阈值（防止误报 drift）
        combined = max(sem_score * 0.7 + lit_score * 0.3, low_threshold + 0.01)
        method = "evolution_dominant"
    else:
        combined = sem_score * 0.7 + lit_score * 0.3
        method = "hybrid"

    confidence = _compute_confidence(lit_score, sem_score)
    verdict, drift = _three_tier_verdict(combined, evo_exempt, high_threshold, low_threshold)

    # 语义兜底
    semantic_verdict = None
    semantic_reasoning = None
    if semantic and (verdict == "ambiguous" or confidence == "low"):
        llm_result = _llm_semantic_judge(orig_texts, current_ctx, combined, verdict, model or "claude")
        if llm_result:
            semantic_verdict = llm_result.get('verdict')
            semantic_reasoning = llm_result.get('reasoning')
            # LLM 修正最终判断
            if semantic_verdict == "aligned":
                verdict = "aligned"
                drift = False
            elif semantic_verdict == "drift":
                verdict = "drift"
                drift = True

    drift_pct = round((1 - combined) * 100, 1)
    explanation = _build_explanation(verdict, sem_score, evolution_tags, current_ctx)

    return DriftReport(
        overlap_score=round(combined, 3),
        literal_score=lit_score,
        semantic_score=sem_score,
        drift_pct=drift_pct,
        drift_detected=drift,
        verdict=verdict,
        confidence=confidence,
        method=method,
        original_scope=orig_d,
        current_scope=current_ctx,
        new_items=current_ctx,
        dropped_items=[],
        evolution_tags=evolution_tags,
        raw_overlap_details={
            'literal': lit_details,
            'semantic': sem_details,
            'thresholds': {'high': high_threshold, 'low': low_threshold},
        },
        semantic_verdict=semantic_verdict,
        semantic_reasoning=semantic_reasoning,
        explanation=explanation,
    )


# ── CLI ──────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys
    p = argparse.ArgumentParser(prog="python -m gate3_drift")
    p.add_argument("--goal", type=Path, required=True)
    p.add_argument("--context", nargs="+", required=True)
    p.add_argument("--threshold", type=float, default=0.50)
    p.add_argument("--semantic", action="store_true")
    p.add_argument("--model", default=None)
    p.add_argument("--high", type=float, default=0.65)
    p.add_argument("--low", type=float, default=0.30)
    a = p.parse_args()
    goal = json.loads(a.goal.read_text(encoding="utf-8"))
    rep = check_gate3(
        goal, a.context,
        threshold=a.threshold, semantic=a.semantic, model=a.model,
        high_threshold=a.high, low_threshold=a.low,
    )
    print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
    sys.exit(0 if not rep.drift_detected else 1)

from pathlib import Path
