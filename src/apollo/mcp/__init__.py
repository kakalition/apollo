"""MCP package: client registry (consume servers) and stdio server (expose Apollo)."""

from __future__ import annotations

from apollo.mcp.registry import MCPRegistry, MCPServer

__all__ = ["MCPRegistry", "MCPServer"]
