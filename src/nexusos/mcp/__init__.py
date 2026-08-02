"""NexusOS MCP server: expose the workspace index over the Model Context Protocol.

The server is a new top layer above ``services`` (like ``cli``): it imports
the read-only search/content-navigation services and the index service, and
publishes them as MCP tools over stdio. Per the AGENTS.md layering rule, the
``mcp`` package is never imported by ``core``, ``workspace``, or
``indexing``.
"""

from __future__ import annotations

from nexusos.mcp.server import build_server

__all__ = ["build_server"]
