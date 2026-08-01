"""Minimal, dependency-free MCP server exposing the three verbs as tools.

Newline-delimited JSON-RPC 2.0 over stdio, per the MCP stdio transport.
Hand-rolled with stdlib only so the repository stays zero-dependency and
fully offline-testable. Exactly three tools — memory_commit,
memory_recall, memory_prove — mirroring the three-verb discipline (G6).
"""
from .server import MCPServer, main

__all__ = ["MCPServer", "main"]
