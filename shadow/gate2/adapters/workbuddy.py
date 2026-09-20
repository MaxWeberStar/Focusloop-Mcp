"""
Workbuddy 适配器（待验证）。
尚未获得 Workbuddy 官方文档；占位实现，待补充接入细节。
"""
from __future__ import annotations

from typing import Any

from .base import (
    AdapterMetadata, HookConfig, MCPConfig, PlatformAdapter,
)


class WorkbuddyAdapter(PlatformAdapter):
    def _init_metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name="workbuddy",
            display_name="Workbuddy",
            version="unknown",
            status="待验证",
            config_paths=[],
            supports_mcp=False,  # 待验证
            supports_hooks=False,  # 待验证
        )

    def generate_mcp_config(self, server: MCPConfig) -> dict[str, Any]:
        raise NotImplementedError(
            "Workbuddy MCP 接入方式待文档验证。"
        )

    def generate_hook_config(self, hook: HookConfig) -> dict[str, Any]:
        raise NotImplementedError("Workbuddy hook 机制待验证")

    def render_install_files(
        self,
        server: MCPConfig,
        hooks: list[HookConfig] | None = None,
    ) -> dict[str, str]:
        return {}


def install_instructions() -> str:
    return """\
Workbuddy 接入方式待验证。

验证步骤：
1. 获取 Workbuddy 官方文档
2. 确认 hook 事件名称与配置格式
3. 模仿 Claude Code 适配器填充
"""
