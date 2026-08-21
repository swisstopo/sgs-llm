"""Public package for the standalone swisstopo search MCP server."""

from .server import build_server

__all__ = ["build_server"]
__version__ = "2.3.0"
