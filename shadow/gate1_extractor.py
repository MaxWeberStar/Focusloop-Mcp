# coding: utf-8
"""Gate 1 constraint extractor - pure rule-based, zero model dependency."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# (compiled_regex, pattern_name) - capture group = constraint text after keyword
NEGATION_PATTERNS = [
    (re.compile(r'\u7981\u6b62(.{5,60}?)[\uff0c\u3002]'), 'forbid'),               # 禁止
    (re.compile(r'(?:\u4e0d\u80fd|\u4e0d\u5f97|\u4e0d\u5e94|\u4e0d\u5141\u8bb8|\u4e0d\u53ef)(.{5,60}?)[\uff0c\u3002]'), 'negation'),  # 不能/不得/不应/不允许/不可
    (re.compile(r'(?:\u53ea\u80fd|\u4ec5\u9650|\u4ec5\u9700|\u53ea)(.{5,60}?)[\uff0c\u3002]'), 'limit'),          # 只能/仅限/仅需/只
    (re.compile(r'\u4e0d\u80fd\u76f4\u63a5\u5f53\u4f5c(.{5,60}?)[\uff0c\u3002]'), 'not_substitute'),     # 不能直接当作
    (re.compile(r'(?:\u6ce8\u610f|\u8b66\u544a|\u5c0f\u5fc3)[:\uff1a](.{5,60}?)[\uff0c\u3002]'), 'warning'),   # 注意/警告/小心
    (re.compile(r'(?:\u5fc5\u987b|\u5e94\u5f53|\u52a1\u5fc5)(.{5,60}?)[\uff0c\u3002]'), 'must'),             # 必须/应当/务必
]

MIN_LEN = 5
MAX_LEN = 120

EXCLUDE_PREFIXES = frozenset([
    '\u6211\u60f3', '\u6211\u6253\u7b97', '\u6211\u8ba1\u5212', '\u6211\u60f3\u8981',
    '\u80fd\u5426', '\u662f\u5426\u53ef\u4ee5', '\u8981\u4e0d\u8981', '\u662f\u5426\u5e94\u8be5',
    '\u4f8b\u5982', '\u6bd4\u5982', '\u5047\u8bbe', '\u4f8b\u5982\u8bf4',
    '\u5982\u679c', '\u8981\u662f', '\u5047\u5982',
])

HIGH_KW = frozenset([
    '\u7981\u6b62', '\u4e0d\u80fd', '\u4e0d\u5f97', '\u4e0d\u5e94', '\u4e0d\u5141\u8bb8',
    '\u53ea\u8bb0\u5f55', '\u4e0d\u81ea\u52a8', '\u4e0d\u4fee\u6539', '\u4e0d\u963b\u65ad',
    '\u4e0d\u80fd\u76f4\u63a5\u5f53\u4f5c', '\u4e0d\u80fd\u5ba3\u79f0',
    '\u672a\u7ecf\u786e\u8ba4', '\u6ca1\u6709\u663e\u5f0f\u786e\u8ba4',
])

@dataclass
class ConstraintCandidate:
    id: str
    text: str
    source: str
    source_detail: str = ''
    confidence: str = 'medium'
    matched_pattern: str = ''
    auto_confirmed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id, 'text': self.text, 'source': self.source,
            'source_detail': self.source_detail, 'confidence': self.confidence,
            'matched_pattern': self.matched_pattern, 'auto_confirmed': self.auto_confirmed,
        }

def _clean(t: str) -> str:
    return t.strip().strip('\uff0c\u3002\uff1a:"\'\u300c\u300d\u300e\u300f')

def _is_excluded(t: str) -> bool:
    return t.startswith(tuple(EXCLUDE_PREFIXES))

def _confidence(t: str, pn: str) -> tuple[str, bool]:
    hits = sum(1 for kw in HIGH_KW if kw in t)
    if hits >= 2 or pn in ('forbid', 'not_substitute'):
        lvl = 'high'
    elif hits == 1 or pn in ('negation', 'warning'):
        lvl = 'medium'
    else:
        lvl = 'low'
    auto = lvl == 'high' and pn in ('forbid', 'not_substitute')
    return lvl, auto

def extract_from_text(text: str, source: str = 'text',
                      source_detail: str = '') -> list[ConstraintCandidate]:
    """Extract constraint candidates from text.

    对完整文本搜索，保留句号作为终结符。
    """
    candidates: list[ConstraintCandidate] = []
    seen: set[str] = set()
    counter = [0]

    def make_id() -> str:
        counter[0] += 1
        return f'c_auto_{counter[0]:03d}'

    # 直接对完整文本搜索（保留句号作为终结符）
    for pattern, pn in NEGATION_PATTERNS:
        for m in pattern.finditer(text):
            extracted = _clean(m.group(1))
            if len(extracted) < MIN_LEN or len(extracted) > MAX_LEN:
                continue
            if _is_excluded(extracted):
                continue
            if extracted in seen:
                continue
            seen.add(extracted)
            lvl, auto = _confidence(extracted, pn)
            candidates.append(ConstraintCandidate(
                id=make_id(), text=extracted, source=source,
                source_detail=source_detail, confidence=lvl,
                matched_pattern=pn, auto_confirmed=auto))

    candidates.sort(key=lambda c: (
        {'high': 0, 'medium': 1, 'low': 2}[c.confidence], -len(c.text)
    ))
    return candidates


def extract_from_event(event: dict[str, Any]) -> list[ConstraintCandidate]:
    """Extract constraint candidates from a FocusLoop hook event.

    从所有角色（user/assistant/system）的消息内容中提取约束。
    """
    candidates: list[ConstraintCandidate] = []
    tool_name = str(event.get('tool_name', ''))
    # 工具参数
    for key, val in (event.get('tool_input') or {}).items():
        if isinstance(val, str) and len(val) > MIN_LEN:
            candidates.extend(extract_from_text(val, 'hook', f'{tool_name}.{key}'))
    # 消息内容（所有角色）
    role = str(event.get('role', ''))
    if role in ('user', 'assistant'):
        for field in ('content', 'text'):
            txt = event.get(field) or ''
            if isinstance(txt, str) and len(txt) > MIN_LEN:
                candidates.extend(extract_from_text(txt, 'hook', f'{role}.{field}'))
    return candidates
if __name__ == "__main__":
    import json, sys
    TESTS = [
        "\u7981\u6b62\u4e0a\u4f20\u672c\u5730\u6587\u4ef6\u5230\u5916\u90e8\u670d\u52a1\u5668\u3002",
        "\u5728\u6ca1\u6709\u7528\u6237\u660e\u786e\u6388\u6743\u524d\uff0c\u4e0d\u80fd\u76f4\u63a5\u8bfb\u53d6\u9879\u76ee\u4ee5\u5916\u7684\u6587\u4ef6\u3002",
        "\u6ce8\u610f\uff1a\u6bcf\u8f6e\u5bf9\u8bdd\u53ea\u5141\u8bb8\u4e00\u6b21\u969c\u65ad\u3002",
        "FocusLoop\u4e0d\u80fd\u76f4\u63a5\u63a8\u65ad\u7528\u6237\u672a\u8868\u8fbe\u7684\u610f\u56fe\u3002",
        "\u81ea\u7136\u8bed\u8a00\u5efa\u8bae\u4e0d\u80fd\u76f4\u63a5\u5f53\u4f5c\u7528\u6237\u786e\u8ba4\u3002",
        "\u5f71\u5b50\u6a21\u5f0f\u9636\u6bb5\u53ea\u8bb0\u5f55\u5224\u65ad\u7ed3\u679c\uff0c\u4e0d\u81ea\u52a8\u969c\u65ad\u6267\u884c\u3002",
        "\u5173\u952e\u8bcd\u53d8\u5316\u3001\u5de5\u5177\u8c03\u7528\u6b21\u6570\u589e\u52a0\u4e0d\u80fd\u5355\u72ec\u4f5c\u4e3a\u6f02\u79fb\u5224\u5b9a\u4f9d\u636e\u3002",
        "\u6211\u60f3\u505a\u4e00\u4e2a\u5e2e\u52a9AI\u805a\u7126\u76ee\u6807\u7684\u5de5\u5177\u3002",
        "\u5fc5\u987b\u5148\u5b8c\u6210Gate2\u624d\u80fd\u8fdb\u5165Gate3\u3002",
    ]
    all_c = []
    for t in TESTS:
        for c in extract_from_text(t, source="demo"):
            d = c.to_dict()
            d["_original"] = t
            all_c.append(d)
            print(f"[{c.confidence}/{c.matched_pattern}] \"{c.text}\" from: {t!r}")
    print(f"\u63d0\u53d6 {len(all_c)} \u4e2a\u5019\u9009\uff08\u6765\u6e90 {len(TESTS)} \u53e5\uff09")
    if "--json" in sys.argv:
        print(json.dumps(all_c, ensure_ascii=False, indent=2))

