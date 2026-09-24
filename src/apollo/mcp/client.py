"""MCP client helpers: build toolsets and health-check configured servers."""

from __future__ import annotations

from typing import Any

from apollo.config import Settings
from apollo.mcp.registry import MCPRegistry


async def check_registry(settings: Settings) -> list[tuple[str, bool, str]]:
    """Connect to each configured server and report its allowlisted tools."""
    registry = MCPRegistry(settings)
    results: list[tuple[str, bool, str]] = []
    if not registry.servers:
        return [("(none)", True, "no MCP servers configured")]
    for name in registry.names():
        server = registry.servers[name]
        try:
            toolset = registry.raw_toolset(name)
            async with toolset:
                tools = await toolset.list_tools()
            allowlist = set(server.spec.allowlist)
            visible = [
                f"{server.namespace}.{t.name}" for t in tools if not allowlist or t.name in allowlist
            ]
            hidden = len(tools) - len(visible)
            detail = (
                f"{server.spec.transport}; visible: {', '.join(visible) or 'none'}"
                + (f"; hidden by allowlist: {hidden}" if hidden else "")
            )
            results.append((name, True, detail))
        except Exception as exc:
            results.append((name, False, f"{type(exc).__name__}: {exc}"))
    return results


async def list_tools(settings: Settings, name: str) -> list[dict[str, Any]]:
    registry = MCPRegistry(settings)
    server = registry.servers[name]
    toolset = registry.raw_toolset(name)
    async with toolset:
        tools = await toolset.list_tools()
    allowlist = set(server.spec.allowlist)
    return [
        {"name": f"{server.namespace}.{t.name}", "description": t.description}
        for t in tools
        if not allowlist or t.name in allowlist
    ]
