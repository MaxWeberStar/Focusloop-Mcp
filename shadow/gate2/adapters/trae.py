"""
Trae 适配器（基于已知文档）。
- MCP 配置: 项目级 .trae/mcp.json 或 IDE 设置中心
- Hooks: Trae IDE 是否支持 hook 事件待验证
"""
from __future__ import annotations

import json
from typing import Any

from .base import (
    AdapterMetadata, HookConfig, MCPConfig, PlatformAdapter,
)


class TraeAdapter(PlatformAdapter):
    def _init_metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name="trae",
            display_name="Trae IDE",
            version="unknown",
            status="已验证",
            config_paths=[".trae/mcp.json"],
            supports_mcp=True,
            supports_hooks=False,  # Trae hook 机制待验证
        )

    def generate_mcp_config(self, server: MCPConfig) -> dict[str, Any]:
        """Trae MCP 配置：与 Claude Code 兼容的 stdio 格式。

        注意：Trae 命令中不能包含空格（文档说明），需要完整路径。
        """
        if server.transport != "stdio":
            raise ValueError("HTTP/SSE MCP 待 Trae 文档进一步验证")
        return {
            "command": server.command,
            "args": server.args,
            "env": server.env,
        }

    def generate_hook_config(self, hook: HookConfig) -> dict[str, Any]:
        """Trae 是否提供 hook 事件接口待验证。"""
        raise NotImplementedError(
            "Trae IDE hook 事件机制待文档验证；"
            "MCP 是当前可行方案"
        )

    def render_install_files(
        self,
        server: MCPConfig,
        hooks: list[HookConfig] | None = None,
    ) -> dict[str, str]:
        """Trae 项目级 MCP 配置。"""
        config = {
            "mcpServers": {
                server.name: self.generate_mcp_config(server)
            }
        }
        return {
            ".trae/mcp.json": json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        }


def install_instructions() -> str:
    return """\
Trae 安装步骤：
1. 在 IDE 模式或 SOLO 模式界面，点击设置图标 → 设置中心
2. 左侧导航选择 MCP，打开 MCP 窗口
3. 右上角点击 添加 > 手动添加
4. 填入生成的 .trae/mcp.json 内容（或粘贴 mcpServers 段）
5. 点击确认

或使用项目级配置：
- 在项目根目录创建 .trae/mcp.json（需在 MCP 设置中启用项目级 MCP）

注意事项（来自 Trae 文档）：
- command 中不能包含空格，否则会解析错误
- Local MCP server 需要本地安装 npx 或 uvx
- 建议使用 NPX 或 UVX 配置
"""
