"""
Gate 1.5 语义扩展器：从约束文本生成多个变体，构建宽松正则。

解决问题：Gate 2 动态规则原本只匹配约束原文（如"使用第三方API"），
        不匹配同语义不同表述（如"调用第三方API"）。

策略：
1. 提取约束中的核心语义单元（动词 + 名词）
2. 对每个单元查同义词表，生成所有变体
3. 用 OR 拼接为宽松正则
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# ── 中文同义词词典 ──────────────────────────────────────
# 格式：key = 标准词，value = 所有等价形式（含 key 自身）
# 分类：modifier（修饰词，不要求在命令中出现）vs core（核心词，要求出现）
SYNONYMS: dict[str, list[str]] = {
    # ── 核心词（动词/对象，命令中应包含） ──
    "使用":    ["使用", "调用", "运行", "执行", "启用", "用", "apply", "use", "invoke", "run"],
    "上传":    ["上传", "传输", "推送", "推到", "同步", "拷贝", "upload", "transfer", "sync", "push", "cp", "copy", "rsync"],
    "下载":    ["下载", "拉取", "获取", "download", "fetch", "pull"],
    "删除":    ["删除", "移除", "删掉", "去掉", "rm", "remove", "delete"],
    "修改":    ["修改", "改动", "编辑", "变更", "edit", "change", "modify", "patch"],
    "读取":    ["读取", "访问", "读", "获取", "read", "access", "fetch"],
    "调用":    ["调用", "使用", "call", "invoke", "apply"],
    "阻断":    ["阻断", "阻止", "拦截", "中止", "block", "abort", "intercept"],
    "API":     ["API", "接口", "端点", "服务", "endpoint", "service"],
    "文件":    ["文件", "文档", "档案", "数据", "file", "document", "doc", "data"],
    "第三方":  ["第三方", "外部", "远端", "third-party", "3rd-party", "external", "remote"],
    "本地":    ["本地", "本机", "local", "localhost"],
    "云端":    ["云端", "云", "云存储", "远程服务器", "远端服务器", "远端", "远程", "cloud", "remote-server", "s3", "drive", "bucket"],
    "数据库":  ["数据库", "DB", "数据表", "database", "db", "sql", "mysql", "postgres"],
    "网络":    ["网络", "互联网", "internet", "network", "http", "https"],
    "包":      ["包", "依赖", "库", "package", "lib", "library", "module"],
    "用户":    ["用户", "使用者", "user", "client"],
}

# 修饰词：识别约束语气，但不出现在目标命令的匹配要求中
MODIFIERS: dict[str, list[str]] = {
    "禁止":    ["禁止", "不允许", "不能", "不得", "不可", "forbid", "prohibit"],
    "必须":    ["必须", "应当", "需要", "务必", "must", "should", "required"],
    "可以":    ["可以", "允许", "可", "may", "can", "allow"],
}


@dataclass
class SemanticExpansion:
    original: str
    variants: list[str]
    regex: str
    tokens_used: list[str]   # 实际查到的同义词词典 key
    method: str              # "rule" / "fallback"

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "variants": self.variants,
            "regex": self.regex,
            "tokens_used": self.tokens_used,
            "method": self.method,
            "variant_count": len(self.variants),
        }


class ConstraintExpander:
    """约束扩展器：把单个约束文本扩展为多个变体 + 宽松正则。"""

    def __init__(
        self,
        synonyms: dict[str, list[str]] | None = None,
        modifiers: dict[str, list[str]] | None = None,
    ) -> None:
        self.synonyms = synonyms if synonyms is not None else SYNONYMS
        self.modifiers = modifiers if modifiers is not None else MODIFIERS

    def _tokenize_chinese(self, text: str) -> list[str]:
        """切出连续的 CJK 片段（2-4字）作为候选语义单元。"""
        out: list[str] = []
        for seq in re.findall(r"[一-鿿]+", text):
            for n in (2, 3, 4):
                for i in range(len(seq) - n + 1):
                    out.append(seq[i:i + n])
        return out

    def _tokenize_english(self, text: str) -> list[str]:
        """提取英文/数字 token。"""
        return re.findall(r"[A-Za-z][A-Za-z0-9_-]+", text)

    def _find_synonyms(self, text: str) -> tuple[list[tuple[str, list[str]]], list[tuple[str, list[str]]]]:
        """从文本中识别可替换的语义单元，返回 (core_hits, modifier_hits) 列表。"""
        core_hits: list[tuple[str, list[str]]] = []
        modifier_hits: list[tuple[str, list[str]]] = []

        # 中文 + 英文 core 词
        for key, variants in self.synonyms.items():
            if key in text:
                if all(k not in [h[0] for h in core_hits] for k in [key]):
                    core_hits.append((key, variants))
        # 英文 core 词不区分大小写
        text_lower = text.lower()
        for key, variants in list(self.synonyms.items()):
            if re.match(r"[A-Za-z]", key):
                kl = key.lower()
                if kl in text_lower and key not in [h[0] for h in core_hits]:
                    variants_l = list({v.lower() for v in variants})
                    core_hits.append((key, variants_l))
        # modifier 词
        for key, variants in self.modifiers.items():
            if key in text:
                modifier_hits.append((key, variants))
        for key, variants in list(self.modifiers.items()):
            if re.match(r"[A-Za-z]", key):
                kl = key.lower()
                if kl in text_lower:
                    variants_l = list({v.lower() for v in variants})
                    modifier_hits.append((key, variants_l))
        return core_hits, modifier_hits

    def expand(self, text: str) -> SemanticExpansion:
        """扩展约束文本，返回变体集合 + 宽松正则。

        策略：core token 用 lookahead（任意顺序）必须出现，modifier 不要求出现。
        """
        core_hits, modifier_hits = self._find_synonyms(text)
        if not core_hits:
            # 没匹配到任何 core 词典项 → 退化为字面匹配
            pattern = f"(?i).*{re.escape(text)}.*"
            return SemanticExpansion(
                original=text, variants=[text], regex=pattern,
                tokens_used=[], method="fallback",
            )

        all_variants: list[str] = [text]
        groups: list[str] = []
        for key, variants in core_hits:
            unique = list({re.escape(v) for v in variants})
            groups.append("(?=.*(?:" + "|".join(unique) + "))")
            all_variants.extend(variants)

        pattern = "(?i).*" + "".join(groups) + ".*"
        return SemanticExpansion(
            original=text,
            variants=sorted(set(all_variants)),
            regex=pattern,
            tokens_used=[k for k, _ in core_hits],
            method="rule",
        )


# ── CLI 测试入口 ────────────────────────────────────────
if __name__ == "__main__":
    import json, sys

    TESTS = [
        "禁止使用第三方API",
        "不能上传本地文件到云端",
        "禁止删除用户数据",
        "禁止网络请求",
        "必须先确认才能修改文件",
        "禁止安装外部包",
    ]

    expander = ConstraintExpander()
    print(f"{'原文':30} {'变体数':6} {'方法':8} {'tokens':30} {'pattern (截断)'}")
    print("-" * 120)
    for t in TESTS:
        r = expander.expand(t)
        pat_short = r.regex[:60] + ("..." if len(r.regex) > 60 else "")
        print(f"{t:30} {len(r.variants):6} {r.method:8} {','.join(r.tokens_used):30} {pat_short}")

    if "--json" in sys.argv:
        results = [expander.expand(t).to_dict() for t in TESTS]
        print("\n" + json.dumps(results, ensure_ascii=False, indent=2))

    # 匹配测试
    print("\n=== 匹配测试 ===")
    match_tests = [
        ("禁止使用第三方API", "curl https://api.example.com", "字面+调用第三方"),
        ("禁止使用第三方API", "调用 第三方接口 获取", "应命中（变体）"),
        ("禁止上传本地文件到云端", "scp local.txt s3://bucket/", "英文+云"),
        ("禁止上传本地文件到云端", "把本地文件推到远端服务器", "中文变体"),
        ("禁止上传本地文件到云端", "cat local.txt", "无关操作"),
    ]
    for orig, cmd, desc in match_tests:
        r = expander.expand(orig)
        matched = bool(re.search(r.regex, cmd))
        status = "✓ 命中" if matched else "✗ 未命中"
        print(f"  [{status}] 约束=\"{orig}\"  cmd=\"{cmd}\" ({desc})")
