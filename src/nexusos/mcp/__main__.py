"""Run the NexusOS MCP server over stdio: ``python -m nexusos.mcp``.

Usage:
    python -m nexusos.mcp [--workspace PATH]

The server speaks the Model Context Protocol over stdin/stdout. MCP clients
launch it as a subprocess and speak JSON-RPC to it; nothing is printed to
stdout except protocol frames. Workspace detection mirrors the CLI: an
explicit ``--workspace`` wins, otherwise the nearest workspace ancestor of
the current directory is used.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nexusos import __version__
from nexusos.core.config import load_config_effective
from nexusos.core.path_safety import find_nearest_workspace_root
from nexusos.mcp.server import build_server


def _resolve_workspace(explicit: str | None) -> Path:
    """Resolve the workspace root, mirroring CLI detection behavior."""
    if explicit:
        return Path(explicit).expanduser().resolve(strict=False)
    detected = find_nearest_workspace_root(Path.cwd())
    if detected is None:
        print(
            "nexusos-mcp: error: no workspace detected; pass --workspace PATH "
            "or run from inside a NexusOS workspace",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return detected


def main(argv: list[str] | None = None) -> None:
    """Entry point for ``python -m nexusos.mcp``."""
    parser = argparse.ArgumentParser(
        prog="python -m nexusos.mcp",
        description="Serve a NexusOS workspace over the Model Context Protocol (stdio).",
    )
    parser.add_argument(
        "--workspace",
        "-w",
        default=None,
        help="Path to the NexusOS workspace root (default: detect from cwd)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"nexusos-mcp {__version__}",
    )
    args = parser.parse_args(argv)

    workspace_root = _resolve_workspace(args.workspace)
    config = load_config_effective(workspace_root)
    if not config.mcp_enabled:
        print(
            "nexusos-mcp: error: MCP server is disabled for this workspace "
            "([mcp] enabled = false in nexusos.toml)",
            file=sys.stderr,
        )
        raise SystemExit(3)
    if config.mcp_transport != "stdio":
        print(
            f"nexusos-mcp: error: unsupported transport {config.mcp_transport!r}; "
            "only 'stdio' is supported today",
            file=sys.stderr,
        )
        raise SystemExit(3)

    server = build_server(workspace_root, config=config)
    # server.run() installs its own anyio event loop, so this must be called
    # from a fresh sync context (not inside an existing asyncio loop).
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
