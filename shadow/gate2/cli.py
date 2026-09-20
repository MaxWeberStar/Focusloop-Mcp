"""Gate2 CLI: rules check / list / add / remove"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .checker import Gate2Checker


def cmd_check(args: argparse.Namespace) -> int:
    checker = Gate2Checker(args.rules)

    # 从 JSON 文件或直接字符串读 tool_input
    if args.input_file:
        tool_input = json.loads(args.input_file.read_text(encoding="utf-8"))
    elif args.input_json:
        tool_input = json.loads(args.input_json)
    else:
        tool_input = {}

    result = checker.check(args.tool, tool_input)
    if result is None:
        # 无输出 = 通过
        return 0

    if result.action == "log":
        print(json.dumps({"status": "logged", **result.to_dict()}, ensure_ascii=False))
        return 0

    # block
    output = {
        "status": "blocked",
        "action": "block",
        "reason": result.user_message.format(match=result.matched_value),
        "gate2": {
            "rule_id": result.rule_id,
            "severity": result.severity,
            "category": result.category,
        },
    }
    print(json.dumps(output, ensure_ascii=False))
    return 2  # 退出码2 = Claude Code hook block 约定


def cmd_list(args: argparse.Namespace) -> int:
    checker = Gate2Checker(args.rules)
    rules = checker.list_rules(category=args.category)
    print(json.dumps({
        "count": len(rules),
        "categories": checker.list_categories(),
        "rules": rules,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    checker = Gate2Checker(args.rules)
    rule = {
        "id": args.id,
        "category": args.category or "user_defined",
        "pattern": args.pattern,
        "tool": args.tool,
        "arg_key": args.arg_key,
        "severity": args.severity,
        "action": args.action,
        "user_message": args.message,
        "constraint_ref": None,
    }
    rule_id = checker.add_rule(rule)
    print(json.dumps({"added": rule_id}, ensure_ascii=False))
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    checker = Gate2Checker(args.rules)
    if checker.remove_rule(args.rule_id):
        print(json.dumps({"removed": args.rule_id}, ensure_ascii=False))
        return 0
    print(json.dumps({"error": f"规则 {args.rule_id} 不存在"}), file=sys.stderr)
    return 1


def cmd_categories(args: argparse.Namespace) -> int:
    checker = Gate2Checker(args.rules)
    cats = checker.list_categories()
    print(json.dumps({"categories": cats}, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gate2.cli")
    parser.add_argument(
        "--rules",
        type=Path,
        default=Path(__file__).parent / "rules.json",
        help="规则文件路径"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # check
    chk = sub.add_parser("check", help="检查工具调用是否触发闸口2")
    chk.add_argument("tool", help="工具名称")
    chk.add_argument("--input-file", type=Path, help="从 JSON 文件读取 tool_input")
    chk.add_argument("--input-json", help="直接传入 tool_input JSON 字符串")
    chk.set_defaults(func=cmd_check)

    # list
    lst = sub.add_parser("list", help="列出所有规则")
    lst.add_argument("--category", help="按类别过滤")
    lst.set_defaults(func=cmd_list)

    # add
    add_p = sub.add_parser("add", help="添加规则")
    add_p.add_argument("id", help="规则 ID")
    add_p.add_argument("pattern", help="正则表达式 pattern")
    add_p.add_argument("tool", default="*", help="工具名称（默认 *）")
    add_p.add_argument("--arg-key", help="参数键（默认 command）")
    add_p.add_argument("--severity", default="medium", choices=["critical","high","medium","low"])
    add_p.add_argument("--action", default="block", choices=["block","log"])
    add_p.add_argument("--message", required=True, help="用户提示消息（支持 {match} 占位）")
    add_p.add_argument("--category", default="user_defined")
    add_p.set_defaults(func=cmd_add, arg_key="command")

    # remove
    rm = sub.add_parser("remove", help="删除规则")
    rm.add_argument("rule_id", help="规则 ID")
    rm.set_defaults(func=cmd_remove)

    # categories
    cats = sub.add_parser("categories", help="列出规则类别")
    cats.set_defaults(func=cmd_categories)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
