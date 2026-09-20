"""Hermes stdio MCP 适配器（已验证）。

Hermes Desktop/CLI 接受生态通用的 ``mcpServers`` JSON 文档；实际运行时由
``hermes mcp add`` 或 Desktop 的 MCP 编辑器保存到当前 profile 的
``mcp_servers`` 配置。项目内 ``.hermes/mcp.json`` 保留为可导入的配置模板。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import (
    AdapterMetadata, HookConfig, MCPConfig, PlatformAdapter,
)


class HermesAdapter(PlatformAdapter):
    def _init_metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name="hermes",
            display_name="Hermes",
            version="0.19.1",
            status="已验证",
            config_paths=[".hermes/mcp.json"],
            supports_mcp=True,
            supports_hooks=True,
        )

    def generate_mcp_config(self, server: MCPConfig) -> dict[str, Any]:
        if server.transport != "stdio":
            raise ValueError("当前 Hermes 适配器仅支持 stdio")
        return {"command": server.command, "args": server.args, "env": server.env}

    def generate_hook_config(self, hook: HookConfig) -> dict[str, Any]:
        if hook.event != "pre_tool_call":
            raise ValueError("FocusLoop Hermes 适配器只生成 pre_tool_call 门禁")
        return {"event": "pre_tool_call", "command": hook.command,
                "when": {"tools": ["terminal", "bash", "shell", "write_file", "patch"]}}

    def render_install_files(
        self,
        server: MCPConfig,
        hooks: list[HookConfig] | None = None,
    ) -> dict[str, str]:
        import json
        hook_path = str((Path.cwd() / ".hermes" / "focusloop_pre_tool_hook.py").resolve())
        hooks_yaml = ("# 合并到 Hermes profile 的 config.yaml hooks: 列表\n"
                      "hooks:\n"
                      f"  - event: pre_tool_call\n    command: \"{hook_path}\"\n"
                      "    when:\n      tools: [terminal, bash, shell, write_file, patch]\n")
        return {".hermes/mcp.json": json.dumps(
            {"mcpServers": {server.name: self.generate_mcp_config(server)}},
            ensure_ascii=False, indent=2) + "\n",
            ".hermes/hooks.yaml": hooks_yaml,
            ".hermes/focusloop_pre_tool_hook.py": Path(
                Path(__file__).resolve().parents[2] / "hermes_pre_tool_hook.py"
            ).read_text(encoding="utf-8"),
        }


def install_instructions() -> str:
    return """\
Hermes stdio MCP 接入已验证（Hermes Agent v0.19.1）。

推荐安装方式：
1. 用 ``python -m gate2.multi_agent_code generate hermes`` 生成
   ``.hermes/mcp.json`` 可导入模板。
2. 在 Hermes Desktop 的“技能与工具 → MCP”粘贴该 JSON，或使用
   ``hermes mcp add focusloop --command <python> --args -m focusloop_mcp_server``。
3. 启动新会话；Hermes 会将已发现工具注册为 ``mcp__focusloop__*``。

Hermes 的 ``pre_tool_call`` Hook 已实现并由 `render_install_files()` 生成；
启用 `.hermes/hooks.yaml` 后可在工具执行前阻断 Gate 2 风险操作。
"""
