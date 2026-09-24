# pyright: reportPrivateImportUsage=false
"""MCP client registry.

Config-declared servers, each default-deny: a server's tools are invisible to
agents unless explicitly allowlisted, and are namespaced before use. Tool
descriptions from servers are untrusted input and are never treated as
instructions (enforced by the agent system prompt + tiered writes).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai.mcp import (  # pyright: ignore[reportPrivateImportUsage]
    MCPToolset,
    SSETransport,
    StdioTransport,
    StreamableHttpTransport,
)

from apollo.config import MCPServerSettings, Settings
from apollo.observability import get_logger

log = get_logger("apollo.mcp")


@dataclass(slots=True)
class MCPServer:
    name: str
    spec: MCPServerSettings

    @property
    def namespace(self) -> str:
        return self.spec.namespace or self.name

    @property
    def is_configured(self) -> bool:
        if self.spec.transport == "stdio":
            return bool(self.spec.command)
        return bool(self.spec.url)


class MCPRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._servers: dict[str, MCPServer] = {
            name: MCPServer(name=name, spec=spec)
            for name, spec in settings.mcp.servers.items()
            if (MCPServer(name=name, spec=spec)).is_configured
        }
        for name, server in list(self._servers.items()):
            if not server.spec.allowlist:
                log.warning("mcp.server_without_allowlist", server=name, detail="all tools denied")

    @property
    def servers(self) -> dict[str, MCPServer]:
        return dict(self._servers)

    def names(self) -> list[str]:
        return sorted(self._servers)

    def raw_toolset(self, name: str) -> MCPToolset[Any]:
        """The unwrapped toolset (used for listing before namespacing/filtering)."""
        server = self._servers[name]
        return MCPToolset(build_transport(server.spec, root=self.settings.root), id=server.name)

    def build_toolset(self, name: str) -> MCPToolset[Any]:
        server = self._servers[name]
        toolset = self.raw_toolset(name)
        allowlist = set(server.spec.allowlist)
        if allowlist:
            toolset = toolset.filtered(lambda _ctx, tool_def, _a=allowlist: tool_def.name in _a)  # type: ignore[assignment]
        else:
            toolset = toolset.filtered(lambda _ctx, _tool_def: False)  # type: ignore[assignment]
        return toolset.prefixed(f"{server.namespace}.")  # type: ignore[return-value]

    def toolsets(self, names: list[str] | None = None) -> list[MCPToolset[Any]]:
        selected = names if names is not None else self.names()
        return [self.build_toolset(name) for name in selected if name in self._servers]


def build_transport(spec: MCPServerSettings, root: Any | None = None) -> Any:
    if spec.transport == "stdio":
        if not spec.command:
            raise ValueError("stdio MCP server requires a command")
        cwd = None
        if root is not None:
            from pathlib import Path

            cwd = str((Path(root) / spec.cwd).resolve()) if spec.cwd else str(Path(root).resolve())
        return StdioTransport(
            command=spec.command[0], args=spec.command[1:], env=spec.env or None, cwd=cwd
        )
    if not spec.url:
        raise ValueError(f"{spec.transport} MCP server requires a url")
    if spec.transport == "sse":
        return SSETransport(url=spec.url)
    return StreamableHttpTransport(url=spec.url)
