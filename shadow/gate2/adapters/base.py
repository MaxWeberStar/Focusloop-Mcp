"""
Adapter 抽象基类：所有平台的统一接口。

每个平台适配器负责：
1. 生成平台专属的 MCP Server 配置
2. 生成平台专属的 Hook 配置
3. 提供 install/uninstall CLI
4. 暴露 schema 给上层 multi_agent_code.py 使用
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MCPConfig:
    """一个 MCP Server 配置块。"""
    name: str
    transport: str  # "stdio" | "http"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class HookConfig:
    """一个 Hook 配置块。"""
    event: str  # "PreToolUse" | "PostToolUse" | "UserPromptSubmit" 等
    matcher: str = ""  # 工具名匹配（regex）
    command: str = ""
    args: list[str] = field(default_factory=list)
    timeout: int = 30


@dataclass
class AdapterMetadata:
    """平台元信息。"""
    name: str                    # "claude_code"
    display_name: str            # "Claude Code"
    version: str = "unknown"
    status: str = "待验证"        # 已验证 / 待验证 / 实验性
    config_paths: list[str] = field(default_factory=list)  # 配置文件相对路径
    supports_mcp: bool = True
    supports_hooks: bool = True


class PlatformAdapter(ABC):
    """平台适配器抽象基类。"""

    def __init__(self) -> None:
        self.metadata: AdapterMetadata = self._init_metadata()

    @abstractmethod
    def _init_metadata(self) -> AdapterMetadata:
        """返回平台元信息。"""

    @abstractmethod
    def generate_mcp_config(self, server: MCPConfig) -> dict[str, Any]:
        """生成平台专属的 MCP 配置 dict（用于写入配置文件）。"""

    @abstractmethod
    def generate_hook_config(self, hook: HookConfig) -> dict[str, Any]:
        """生成平台专属的 hook 配置 dict。"""

    @abstractmethod
    def render_install_files(
        self,
        server: MCPConfig,
        hooks: list[HookConfig] | None = None,
    ) -> dict[str, str]:
        """返回 {文件路径: 文件内容} 字典，安装到目标平台。

        Args:
            server: FocusLoop MCP Server 配置
            hooks: 要注册的 hook 列表

        Returns:
            文件路径 → 内容的映射。调用方负责实际写入。
        """

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} status={self.metadata.status}>"


# shadow 目录（本文件位于 shadow/gate2/adapters/base.py）
SHADOW_DIR = Path(__file__).resolve().parents[2]


def _default_python(shadow_dir: Path = SHADOW_DIR) -> str:
    """优先使用 shadow 自带 venv 的 python（已装 mcp 依赖），否则回退 python3。"""
    venv_python = shadow_dir / ".venv" / "bin" / "python3"
    return str(venv_python) if venv_python.exists() else "python3"


def _space_free_launcher(python_path: str) -> str:
    """Trae 会把 MCP 配置的 command 按空格切分，路径含空格会导致 spawn ENOENT。

    若 python 路径含空格，则在无空格目录生成一个转发 shim，并返回 shim 路径。
    """
    if " " not in python_path:
        return python_path
    for bin_dir in (Path.home() / ".local" / "bin", Path("/tmp")):
        if " " in str(bin_dir):
            continue
        bin_dir.mkdir(parents=True, exist_ok=True)
        shim = bin_dir / "focusloop-python"
        shim.write_text(
            "#!/bin/sh\n"
            "# FocusLoop python shim（路径含空格时的 Trae 兼容层）\n"
            f'exec "{python_path}" "$@"\n',
            encoding="utf-8",
        )
        shim.chmod(0o755)
        return str(shim)
    return python_path


def default_focusloop_server(
    python_path: str | None = None,
    project_dir: Path | None = None,
) -> MCPConfig:
    """返回 FocusLoop MCP Server 的标准配置（所有平台共用）。

    v2 统一 Server 暴露 Gate 1 / 1.5 / 2 / 3 + Goal 管理所有能力。

    宿主（Trae/Claude Code/Codex）启动 MCP Server 时的 cwd 不固定，
    因此这里全部使用绝对路径 + PYTHONPATH，保证从任意 cwd 均可启动。
    """
    shadow_dir = SHADOW_DIR
    db_path = (
        Path(project_dir).expanduser().resolve() / ".focusloop" / "state.sqlite3"
        if project_dir
        else shadow_dir / ".focusloop" / "state.sqlite3"
    )
    return MCPConfig(
        name="focusloop",
        transport="stdio",
        command=_space_free_launcher(python_path or _default_python(shadow_dir)),
        args=["-m", "focusloop_mcp_server"],
        env={
            "PYTHONPATH": str(shadow_dir),
            "FOCUSLOOP_DB": str(db_path),
            "FOCUSLOOP_PROJECT": (
                Path(project_dir).expanduser().resolve().name
                if project_dir else "focusloop-v1"
            ),
            "FOCUSLOOP_RULES": str(shadow_dir / "gate2" / "rules.json"),
        },
    )


def default_focusloop_hooks(python_path: str = "python3") -> list[HookConfig]:
    """返回 FocusLoop Hook 的标准配置（用于平台 hook 接入）。"""
    return [
        HookConfig(event="UserPromptSubmit", matcher="",
                   command=python_path, args=["focusloop.py", "hook"]),
        HookConfig(event="PreToolUse", matcher="",
                   command=python_path, args=["focusloop.py", "hook"]),
        HookConfig(event="PostToolUse", matcher="",
                   command=python_path, args=["focusloop.py", "hook"]),
    ]
