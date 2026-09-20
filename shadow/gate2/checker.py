"""Gate2Checker: 纯规则引擎，零模型依赖，平台无关"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Gate2Result:
    """闸口2检测结果"""
    rule_id: str
    category: str
    severity: str       # critical / high / medium / low
    action: str         # block / log
    user_message: str
    matched_value: str
    tool_name: str
    arg_key: str | None
    rule_ref: str | None  # constraint_ref

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "action": self.action,
            "user_message": self.user_message,
            "matched_value": self.matched_value,
            "tool_name": self.tool_name,
            "arg_key": self.arg_key,
            "constraint_ref": self.rule_ref,
        }


class Gate2Checker:
    """
    闸口2规则检查器。
    
    特性：
    - 纯规则，无模型依赖
    - 平台无关（只依赖 tool_name + tool_input）
    - 支持热更新规则（reload()）
    - 支持动态添加/删除规则
    """

    def __init__(self, rules_path: Path | str, store: Any | None = None) -> None:
        self.rules_path = Path(rules_path)
        self.store = store
        self._rules: dict[str, Any] | None = None
        self._dynamic_rules: list[dict[str, Any]] = []

    @property
    def rules(self) -> dict[str, Any]:
        if self._rules is None:
            self._load()
        return self._rules

    def _load(self) -> None:
        if not self.rules_path.exists():
            raise FileNotFoundError(f"规则文件不存在: {self.rules_path}")
        self._rules = json.loads(self.rules_path.read_text(encoding="utf-8"))

    def reload(self) -> None:
        """强制重新加载规则文件"""
        self._rules = None
        self._load()

    # ── Gate 1 动态约束加载 ────────────────────────────────

    def sync_from_store(self, project: str | None = None) -> int:
        """从 Store 的 confirmed_constraint 列表中生成动态规则。

        Returns:
            生成的动态规则数（新增或更新）。
        """
        if self.store is None:
            return 0
        if project is None:
            project = self.store.project

        confirmed_rows = self.store.db.execute(
            "SELECT id, payload FROM observations WHERE id LIKE ?",
            ("confirmed_constraint:%",)
        ).fetchall()
        rejected_ids = {
            r[0].split(":", 1)[1] for r in
            self.store.db.execute(
                "SELECT id FROM observations WHERE id LIKE ?",
                ("rejected_constraint:%",)
            ).fetchall()
        }

        new_rules: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for row in confirmed_rows:
            cid = row[0].split(":", 1)[1]
            if cid in rejected_ids:
                # 已拒绝，跳过
                continue
            payload = json.loads(row[1])
            text = payload.get("text", "")
            if not text or cid in seen_ids:
                continue
            seen_ids.add(cid)
            new_rules.append(self._build_dynamic_rule(cid, payload))

        self._dynamic_rules = new_rules
        return len(new_rules)

    def _build_dynamic_rule(self, cid: str, payload: dict[str, Any]) -> dict[str, Any]:
        """把一条 confirmed constraint 转换为 Gate 2 动态规则。

        使用 Gate 1.5 语义扩展器生成宽松正则（同义词变体、任意顺序匹配）。
        """
        text = payload.get("text", "")
        pattern = f"(?i).*{re.escape(text)}.*"
        method = "literal"
        variants_count = 1
        tokens_used: list[str] = []
        try:
            from gate1_5_semantic import ConstraintExpander
            expander = ConstraintExpander()
            expansion = expander.expand(text)
            if expansion.method == "rule" and expansion.tokens_used:
                pattern = expansion.regex
                method = "semantic"
                variants_count = len(expansion.variants)
                tokens_used = expansion.tokens_used
        except Exception:
            pass

        return {
            "id": f"dyn-{cid}",
            "category": "user_constraint",
            "pattern": pattern,
            "tool": "*",
            "arg_key": "command",
            "severity": "high",
            "action": "block",
            "user_message": f"违反用户已确认约束 {cid}: {{match}}",
            "constraint_ref": cid,
            "_source": "gate1_confirmed",
            "_confidence": payload.get("confidence", "medium"),
            "_match_method": method,
            "_variants_count": variants_count,
            "_semantic_tokens": tokens_used,
        }

    def _all_rules(self) -> list[dict[str, Any]]:
        """所有规则（静态 + dynamic）"""
        return list(self.rules.get("rules", [])) + self._dynamic_rules

    # ── 公开 API ──────────────────────────────────────────

    def check(self, tool_name: str, tool_input: dict[str, Any]) -> Gate2Result | None:
        """
        检查单个工具调用是否触发闸口2规则。
        
        Args:
            tool_name: 工具名称（如 "Bash", "Write", "Edit"）
            tool_input: 工具参数字典
            
        Returns:
            None → 通过检查
            Gate2Result → 触发规则
        """
        for rule in self._all_rules():
            if self._rule_matches(rule, tool_name, tool_input):
                return self._build_result(rule, tool_name, tool_input)
        return None

    def check_batch(
        self, events: list[dict[str, Any]]
    ) -> list[tuple[int, Gate2Result]]:
        """
        批量检查事件列表。
        
        Args:
            events: [{"tool_name": ..., "tool_input": ...}, ...]
            
        Returns:
            [(index, Gate2Result), ...] — 所有触发规则的事件索引和结果
        """
        results: list[tuple[int, Gate2Result]] = []
        for i, event in enumerate(events):
            tool_name = event.get("tool_name", "")
            tool_input = event.get("tool_input", {})
            result = self.check(tool_name, tool_input)
            if result is not None:
                results.append((i, result))
        return results

    def add_rule(self, rule: dict[str, Any]) -> str:
        """动态添加规则，返回 rule_id"""
        rules = self.rules
        rule_id = rule.get("id")
        if not rule_id:
            raise ValueError("规则必须包含 id")
        existing = {r["id"] for r in rules.get("rules", [])}
        if rule_id in existing:
            raise ValueError(f"规则 ID {rule_id} 已存在")
        rules["rules"].append(rule)
        self.rules_path.write_text(
            json.dumps(rules, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        self.reload()
        return rule_id

    def remove_rule(self, rule_id: str) -> bool:
        """删除规则，成功返回 True"""
        rules = self.rules
        before = len(rules["rules"])
        rules["rules"] = [r for r in rules["rules"] if r["id"] != rule_id]
        if len(rules["rules"]) < before:
            self.rules_path.write_text(
                json.dumps(rules, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            self.reload()
            return True
        return False

    def list_rules(self, category: str | None = None) -> list[dict[str, Any]]:
        """列出规则，可选按 category 过滤"""
        all_rules = self.rules.get("rules", [])
        if category:
            return [r for r in all_rules if r.get("category") == category]
        return all_rules

    def list_categories(self) -> list[str]:
        """列出所有规则类别"""
        cats = {r.get("category") for r in self.rules.get("rules", [])}
        return sorted(cats)

    # ── 内部实现 ──────────────────────────────────────────

    def _rule_matches(self, rule: dict, tool_name: str, tool_input: dict) -> bool:
        """判断规则是否匹配工具调用"""
        # 工具名匹配
        pattern_tool = rule.get("tool", "*")
        if not self._tool_matches(tool_name, pattern_tool):
            return False

        # 参数匹配
        if not self._input_matches(tool_input, rule):
            return False

        return True

    def _tool_matches(self, tool_name: str, pattern: str) -> bool:
        if pattern == "*":
            return True
        # 支持带通配符的工具名，如 "Bash" / "*"
        pattern_lower = pattern.lower()
        tool_lower = tool_name.lower()
        if "*" in pattern_lower:
            import fnmatch
            return fnmatch.fnmatch(tool_lower, pattern_lower)
        return tool_lower == pattern_lower

    def _input_matches(self, tool_input: dict, rule: dict) -> bool:
        arg_key = rule.get("arg_key")
        if arg_key is None:
            # arg_key 为空时，只有当工具名本身就是拦截目标时才匹配
            # 此时 tool pattern 必须非 "*"，pattern 实际匹配工具名
            tool_pattern = rule.get("tool", "*")
            if tool_pattern == "*":
                return True  # 通配所有工具 = 无实际检查 = 跳过
            # 有具体工具限制，但没有参数键 → 用 pattern 直接匹配工具名
            # 这很少见，保守返回 False
            return False

        value = self._extract_value(tool_input, arg_key)
        if value is None:
            return False

        pattern = rule.get("pattern", "")
        if not pattern:
            return True

        try:
            matched = re.search(pattern, str(value), re.IGNORECASE)
            if not matched:
                return False
            # 白名单：常见的合法清理操作不应被拦截
            matched_str = matched.group(0)
            value_str = str(value)
            # rm -rf __pycache__ / .cache / node_modules 是常见合法清理；
            # .git 是项目版本历史与配置，不属于安全清理白名单。
            safe_cleanup_patterns = [
                ('rm', '-rf', '__pycache__'),
                ('rm', '-rf', '.cache'),
                ('rm', '-rf', 'node_modules'),
                ('rm', '-rf', '.pytest_cache'),
                ('rm', '-rf', '.mypy_cache'),
                ('rm', '-rf', '.venv'),
            ]
            import re as _re
            for safe in safe_cleanup_patterns:
                # 宽松匹配：只要命令中包含这些组合就排除
                if all(part in value_str for part in safe):
                    return False
            return True
        except re.error:
            return False

    def _extract_value(self, tool_input: dict, arg_key: str) -> str | None:
        """
        支持 dotted.key 路径，如 "command" 或 "exec.command"。
        也支持列表索引，如 "calls.0.name"。
        """
        keys = arg_key.split(".")
        value: Any = tool_input
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            elif isinstance(value, list):
                try:
                    idx = int(k)
                    value = value[idx]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return str(value) if value is not None else None

    def _build_result(self, rule: dict, tool_name: str, tool_input: dict) -> Gate2Result:
        matched = self._extract_matched_value(tool_input, rule)
        return Gate2Result(
            rule_id=rule["id"],
            category=rule.get("category", "unknown"),
            severity=rule.get("severity", "medium"),
            action=rule.get("action", "block"),
            user_message=rule.get("user_message", "检测到异常操作，是否继续？"),
            matched_value=matched,
            tool_name=tool_name,
            arg_key=rule.get("arg_key"),
            rule_ref=rule.get("constraint_ref"),
        )

    def _extract_matched_value(self, tool_input: dict, rule: dict) -> str:
        arg_key = rule.get("arg_key")
        if arg_key is None:
            return str(tool_input)[:80]
        value = self._extract_value(tool_input, arg_key)
        if value is None:
            return ""
        pattern = rule.get("pattern", "")
        try:
            m = re.search(pattern, str(value), re.IGNORECASE)
            return m.group(0) if m else str(value)[:80]
        except re.error:
            return str(value)[:80]


# ── 独立 CLI 入口 ──────────────────────────────────────────────

def check_tool(tool_name: str, tool_input: dict[str, Any], rules_path: Path) -> Gate2Result | None:
    checker = Gate2Checker(rules_path)
    return checker.check(tool_name, tool_input)
