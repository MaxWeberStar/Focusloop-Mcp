"""
multi_agent_code: FocusLoop 多平台适配统一入口。

统一调度所有平台适配器，提供：
1. 列出所有支持平台 + 当前验证状态
2. 为指定平台生成配置文件
3. 安装到目标平台项目目录
4. 验证配置文件正确性
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 确保 gate2 模块可导入
sys.path.insert(0, str(Path(__file__).parent.parent))

from gate2.adapters.base import (
    PlatformAdapter, MCPConfig, HookConfig,
    default_focusloop_server, default_focusloop_hooks,
)


# 适配器注册表
ADAPTERS: dict[str, type[PlatformAdapter]] = {}


def _register_all() -> None:
    """懒加载所有适配器（避免导入失败时整体无法使用）。"""
    if ADAPTERS:
        return
    from gate2.adapters.claude_code import ClaudeCodeAdapter
    from gate2.adapters.codex import CodexAdapter
    from gate2.adapters.trae import TraeAdapter
    from gate2.adapters.hermes import HermesAdapter
    from gate2.adapters.workbuddy import WorkbuddyAdapter
    from gate2.adapters.dsh_harness import DSHHarnessAdapter

    ADAPTERS["claude_code"] = ClaudeCodeAdapter
    ADAPTERS["codex"] = CodexAdapter
    ADAPTERS["trae"] = TraeAdapter
    ADAPTERS["hermes"] = HermesAdapter
    ADAPTERS["workbuddy"] = WorkbuddyAdapter
    ADAPTERS["dsh_harness"] = DSHHarnessAdapter


def list_platforms() -> list[dict]:
    """返回所有平台的状态列表。"""
    _register_all()
    out = []
    for name, cls in ADAPTERS.items():
        meta = cls().metadata
        out.append({
            "name": meta.name,
            "display_name": meta.display_name,
            "version": meta.version,
            "status": meta.status,
            "supports_mcp": meta.supports_mcp,
            "supports_hooks": meta.supports_hooks,
            "config_paths": meta.config_paths,
        })
    return out


def get_adapter(name: str) -> PlatformAdapter:
    _register_all()
    if name not in ADAPTERS:
        raise ValueError(
            f"未知平台: {name}. 可用: {', '.join(ADAPTERS.keys())}"
        )
    return ADAPTERS[name]()


def generate_config(platform: str, target_dir: Path) -> dict[str, str]:
    """为目标平台生成配置文件内容。

    Returns:
        {相对路径: 文件内容} 字典
    """
    adapter = get_adapter(platform)
    server = default_focusloop_server(project_dir=target_dir)
    hooks = default_focusloop_hooks()
    return adapter.render_install_files(server, hooks)


def install(platform: str, target_dir: Path, dry_run: bool = False) -> list[str]:
    """为目标平台生成并写入配置文件。

    Returns:
        写入的文件路径列表（绝对路径）。
    """
    adapter = get_adapter(platform)
    if not adapter.metadata.supports_mcp and not adapter.metadata.supports_hooks:
        print(f"⚠️  {platform} 当前状态: {adapter.metadata.status}", file=sys.stderr)
        print(f"   显示名: {adapter.metadata.display_name}", file=sys.stderr)
        print(f"   配置文件路径: {adapter.metadata.config_paths or '(未提供)'}", file=sys.stderr)
        print(f"   接入方法请参考适配器 install_instructions()", file=sys.stderr)
        return []

    files = generate_config(platform, target_dir)
    written = []
    for rel_path, content_text in files.items():
        # 处理 ~/ 路径 — 需要用户显式确认
        if rel_path.startswith("~"):
            full_path = Path(rel_path).expanduser()
            if not dry_run:
                confirm = input(f"⚠️  将写入全局配置 {full_path}（可能覆盖现有 Codex/MCP 设置）。继续？(y/N): ").strip().lower()
                if confirm != 'y':
                    print(f"  ⊘ 跳过 {rel_path}（用户取消）")
                    continue
        else:
            full_path = target_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        if dry_run:
            print(f"  [DRY-RUN] Would write: {full_path}")
        else:
            full_path.write_text(content_text, encoding="utf-8")
            written.append(str(full_path))
            print(f"  ✓ Wrote: {full_path}")
    return written


def validate_config(platform: str, target_dir: Path) -> dict:
    """验证目标平台的配置文件是否符合预期。"""
    adapter = get_adapter(platform)
    meta = adapter.metadata
    result = {
        "platform": platform,
        "status": meta.status,
        "expected_files": meta.config_paths,
        "found_files": [],
        "issues": [],
    }
    for path_str in meta.config_paths:
        full_path = Path(path_str).expanduser()
        if not full_path.is_absolute():
            full_path = target_dir / path_str
        if full_path.exists():
            result["found_files"].append(str(full_path))
            try:
                json.loads(full_path.read_text(encoding="utf-8"))
                result.setdefault("valid_files", []).append(str(full_path))
            except json.JSONDecodeError as e:
                result["issues"].append(
                    f"{full_path}: JSON 解析错误 - {e}"
                )
        else:
            result["issues"].append(
                f"{full_path}: 文件不存在"
            )
    return result


# ── CLI ────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="multi_agent_code",
        description="FocusLoop 多平台适配统一入口",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出所有支持的平台及验证状态")

    gen = sub.add_parser("generate", help="为目标平台生成配置文件")
    gen.add_argument("platform", help="平台名")
    gen.add_argument("--target", type=Path, default=Path("."),
                     help="目标项目目录（默认当前目录）")

    inst = sub.add_parser("install", help="安装配置到目标平台项目")
    inst.add_argument("platform", help="平台名")
    inst.add_argument("--target", type=Path, default=Path("."),
                     help="目标项目目录")
    inst.add_argument("--dry-run", action="store_true",
                      help="只显示将要写入的文件，不实际写入")

    val = sub.add_parser("validate", help="验证目标平台的配置文件")
    val.add_argument("platform", help="平台名")
    val.add_argument("--target", type=Path, default=Path("."),
                     help="目标项目目录")

    args = parser.parse_args()

    if args.command == "list":
        platforms = list_platforms()
        print(f"{'Platform':15} {'Display':20} {'Status':25} MCP Hooks")
        print("-" * 80)
        for p in platforms:
            print(f"{p['name']:15} {p['display_name']:20} "
                  f"{p['status']:25} "
                  f"{'✓' if p['supports_mcp'] else '✗':3} "
                  f"{'✓' if p['supports_hooks'] else '✗':3}")
        return 0

    if args.command == "generate":
        try:
            files = generate_config(args.platform, args.target)
            for rel_path, content in files.items():
                print(f"=== {rel_path} ===")
                print(content)
                print()
        except NotImplementedError as e:
            print(f"❌ {args.platform}: {e}", file=sys.stderr)
            return 1
        return 0

    if args.command == "install":
        try:
            written = install(args.platform, args.target, dry_run=args.dry_run)
            if not written and not args.dry_run:
                print(f"⚠️  {args.platform} 暂无可写入文件（可能功能未实现）")
                return 1
        except NotImplementedError as e:
            print(f"❌ {args.platform}: {e}", file=sys.stderr)
            return 1
        return 0

    if args.command == "validate":
        result = validate_config(args.platform, args.target)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not result["issues"] else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
