"""Registry for custom Cavalry AYON panel tool handlers."""

from __future__ import annotations

_cavalry_tool_handlers: dict = {}


def register_cavalry_tool_handler(tool_name: str, handler) -> None:
    """Register a main-thread handler for a Cavalry panel ``/tool`` request."""
    _cavalry_tool_handlers[str(tool_name)] = handler


def unregister_cavalry_tool_handler(tool_name: str) -> None:
    """Remove a previously registered Cavalry panel tool handler."""
    _cavalry_tool_handlers.pop(str(tool_name), None)


def get_cavalry_tool_handler(tool_name: str):
    """Return a registered handler, if any."""
    return _cavalry_tool_handlers.get(tool_name)


def registered_cavalry_tool_names():
    """Return names of registered custom panel tools."""
    return set(_cavalry_tool_handlers.keys())
