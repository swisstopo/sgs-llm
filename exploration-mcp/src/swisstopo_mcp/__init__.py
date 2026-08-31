"""Public package for the standalone swisstopo search MCP server."""

from .server import build_server

__all__ = ["build_server"]
__version__ = "3.1.0"
