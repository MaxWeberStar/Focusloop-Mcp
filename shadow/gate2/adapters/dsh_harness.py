"""
DSH Harness 适配器（待验证）。
DSH Harness 仍在迭代中，参考：https://github.com/topics/dsh-plugin
占位实现，等官方接口稳定后填充。
"""
from __future__ import annotations

from typing import Any

from .base import (
    AdapterMetadata, HookConfig, MCPConfig, PlatformAdapter,
)


class DSHHarnessAdapter(PlatformAdapter):
    def _init_metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name="dsh_harness",
            display_name="DSH Harness",
            version="dev",
            status="待验证（项目仍在迭代）",
            config_paths=[],
            supports_mcp=False,  # 待验证
            supports_hooks=False,  # 待验证
        )

    def generate_mcp_config(self, server: MCPConfig) -> dict[str, Any]:
        raise NotImplementedError(
            "DSH Harness MCP 接入待插件机制稳定后验证。"
        )

    def generate_hook_config(self, hook: HookConfig) -> dict[str, Any]:
        raise NotImplementedError("DSH Harness hook 机制待验证")

    def render_install_files(
        self,
        server: MCPConfig,
        hooks: list[HookConfig] | None = None,
    ) -> dict[str, str]:
        return {}


def install_instructions() -> str:
    return """\
DSH Harness 接入方式待验证。

参考：https://github.com/topics/dsh-plugin

验证步骤：
1. 跟踪 dsh-plugin 项目进展，确认 hook/MCP 接入 API
2. 模仿其他适配器填充实现
"""
