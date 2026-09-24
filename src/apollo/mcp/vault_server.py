"""Standalone stdio MCP server exposing the markdown vault (path-sandboxed).

Launched by the MCP client registry (see ``apollo.toml``). It never escapes the
configured vault root and performs no network access.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from apollo.tools.vault import Vault


def _vault() -> Vault:
    root = os.environ.get("APOLLO_VAULT_ROOT", "data/vault")
    return Vault(Path(root))


def build_server() -> MCPServer:
    server = MCPServer(name="apollo-vault", instructions="Read/write/search markdown notes in the Apollo vault.")

    @server.tool(description="Read a markdown note by vault-relative path.")
    def read(path: str) -> str:
        return _vault().read(path)

    @server.tool(description="Write a markdown note by vault-relative path.")
    def write(path: str, content: str) -> dict[str, str]:
        rel = _vault().write(path, content)
        return {"path": rel}

    @server.tool(description="List markdown notes (vault-relative paths).")
    def list_notes(pattern: str = "**/*.md") -> list[str]:
        vault = _vault()
        return [str(p.relative_to(vault.root)) for p in vault.list_docs(pattern)]

    @server.tool(description="Lexically search the vault and return matching paths with a snippet.")
    def search(query: str, limit: int = 10) -> list[dict[str, str]]:
        vault = _vault()
        needle = query.lower()
        hits: list[dict[str, str]] = []
        for path in vault.list_docs():
            text = path.read_text(encoding="utf-8")
            if needle in text.lower():
                idx = text.lower().index(needle)
                snippet = text[max(0, idx - 80) : idx + 120].replace("\n", " ")
                hits.append({"path": str(path.relative_to(vault.root)), "snippet": snippet})
            if len(hits) >= limit:
                break
        return hits

    return server


def main() -> None:
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
