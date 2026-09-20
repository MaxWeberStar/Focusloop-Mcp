"""
Claude Code 适配器（已验证）。
- Hook 配置: .claude/settings.local.json (项目级) 或 ~/.claude/settings.json (全局)
- MCP 配置: claude mcp add 命令 或 .mcp.json
"""
from __future__ import annotations

import json
from typing import Any

from .base import (
    AdapterMetadata, HookConfig, MCPConfig, PlatformAdapter,
)


class ClaudeCodeAdapter(PlatformAdapter):
    def _init_metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name="claude_code",
            display_name="Claude Code",
            version="1.x",
            status="已验证",
            config_paths=[".claude/settings.local.json", ".mcp.json"],
            supports_mcp=True,
            supports_hooks=True,
        )

    def generate_mcp_config(self, server: MCPConfig) -> dict[str, Any]:
        """Claude Code 的 stdio MCP 配置格式。"""
        if server.transport != "stdio":
            raise ValueError("Claude Code 仅支持 stdio MCP server")
        return {
            "command": server.command,
            "args": server.args,
            "env": server.env,
        }

    def generate_hook_config(self, hook: HookConfig) -> dict[str, Any]:
        """Claude Code 的 hook entry 格式。"""
        return {
            "matcher": hook.matcher,
            "hooks": [{
                "type": "command",
                "command": hook.command,
                "args": hook.args,
                "timeout": hook.timeout,
            }],
        }

    def render_install_files(
        self,
        server: MCPConfig,
        hooks: list[HookConfig] | None = None,
    ) -> dict[str, str]:
        """返回 Claude Code 项目级配置文件内容。"""
        result: dict[str, str] = {}

        # 1. .mcp.json (MCP server 配置)
        mcp_json = {
            "mcpServers": {
                server.name: self.generate_mcp_config(server)
            }
        }
        result[".mcp.json"] = json.dumps(mcp_json, ensure_ascii=False, indent=2)

        # 2. .claude/settings.local.json (hook + mcp 配置)
        settings: dict[str, Any] = {"hooks": {}}
        if hooks:
            for hook in hooks:
                event = hook.event
                if event not in settings["hooks"]:
                    settings["hooks"][event] = []
                settings["hooks"][event].append(self.generate_hook_config(hook))
        result[".claude/settings.local.json"] = json.dumps(
            settings, ensure_ascii=False, indent=2
        )

        return result


def install_instructions() -> str:
    return """\
Claude Code 安装步骤：
1. 复制生成的 .mcp.json 到项目根目录
2. 复制生成的 .claude/settings.local.json 到项目根目录
3. 在 Claude Code 中执行: claude mcp add focusloop
4. 重启 Claude Code 会话使 hooks 生效

或通过命令行快速安装（推荐）：
  claude mcp add --scope project focusloop -- python3 -m gate2.mcp_server
"""
