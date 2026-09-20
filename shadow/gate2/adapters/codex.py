"""
Codex 适配器（已验证）。
- Hook 配置: ~/.Codex.json (MCP 部分) + 项目级 hooks 配置
- MCP 配置: ~/.Codex.json
"""
from __future__ import annotations

import json
from typing import Any

from .base import (
    AdapterMetadata, HookConfig, MCPConfig, PlatformAdapter,
)


class CodexAdapter(PlatformAdapter):
    def _init_metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name="codex",
            display_name="Codex",
            version="MiniMax-M3",
            status="已验证",
            config_paths=["~/.Codex.json"],
            supports_mcp=True,
            supports_hooks=False,  # Codex 暂未对外开放 hook 事件
        )

    def generate_mcp_config(self, server: MCPConfig) -> dict[str, Any]:
        """Codex 的 stdio MCP 配置（与 Claude Code 相同格式）。"""
        if server.transport != "stdio":
            raise ValueError("Codex stdio MCP 暂未实现")
        return {
            "command": server.command,
            "args": server.args,
            "env": server.env,
        }

    def generate_hook_config(self, hook: HookConfig) -> dict[str, Any]:
        """Codex 暂不支持 hook 事件（保留接口以备未来）。"""
        raise NotImplementedError(
            "Codex 暂未对外开放 hook 事件接口；"
            "MCP 是当前唯一可行接入方式"
        )

    def render_install_files(
        self,
        server: MCPConfig,
        hooks: list[HookConfig] | None = None,
    ) -> dict[str, str]:
        """Codex 仅生成 MCP 配置，不生成 hook 配置。"""
        config = {
            "mcpServers": {
                server.name: self.generate_mcp_config(server)
            }
        }
        return {
            "~/.Codex.json": json.dumps(config, ensure_ascii=False, indent=2),
        }


def install_instructions() -> str:
    return """\
Codex 安装步骤：
1. 打开 ~/.Codex.json（Codex MCP 配置中心）
2. 把生成的配置合并到现有 mcpServers 段
3. 重启 Codex

注意：Codex 当前通过 MCP 接入，hooks 事件未开放。
"""
