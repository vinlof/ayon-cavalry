"""Load Cavalry AYON panel tool handlers declared by other addons."""

from __future__ import annotations

import importlib
import json
import logging
import os
from typing import Any, Callable

from .panel_tool_registry import (
    register_cavalry_tool_handler,
    registered_cavalry_tool_names,
)

log = logging.getLogger(__name__)

PANEL_TOOL_HANDLERS_MANIFEST = "ayon_panel_tool_handlers.json"

_BUILTIN_PANEL_TOOLS = frozenset({
    "loader",
    "publisher",
    "workfiles",
    "creator",
    "sceneinventory",
})


def is_registered_panel_tool(tool_name: str) -> bool:
    """Return whether ``tool_name`` is a built-in or registered custom panel tool."""
    if tool_name == "set_settings":
        return True
    if tool_name in _BUILTIN_PANEL_TOOLS:
        return True
    return tool_name in registered_cavalry_tool_names()


def _import_handler(entry: dict[str, Any]) -> Callable[..., Any] | None:
    module_name = str(entry.get("module") or "").strip()
    callable_name = str(entry.get("callable") or "").strip()
    if not module_name or not callable_name:
        return None
    module = importlib.import_module(module_name)
    handler = getattr(module, callable_name, None)
    if not callable(handler):
        raise TypeError(
            f"{module_name}.{callable_name} is not callable"
        )
    return handler


def load_panel_tool_handlers_from_manifest(scripts_dir: str) -> int:
    """Import and register handlers listed in the AYON panel tools manifest.

    Args:
        scripts_dir: ``Cavalry/Scripts/AYON`` directory (same folder as ayon_config.json).

    Returns:
        Number of handlers registered successfully.
    """
    manifest_path = os.path.join(scripts_dir, PANEL_TOOL_HANDLERS_MANIFEST)
    if not os.path.isfile(manifest_path):
        return 0

    try:
        with open(manifest_path, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        log.warning(
            "Could not read panel tool handlers manifest: %s",
            manifest_path,
            exc_info=True,
        )
        return 0

    entries = data.get("handlers") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        log.warning(
            "Invalid panel tool handlers manifest (missing handlers list): %s",
            manifest_path,
        )
        return 0

    registered = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        tool_name = str(entry.get("tool") or "").strip()
        if not tool_name:
            continue
        try:
            handler = _import_handler(entry)
            if handler is None:
                continue
            register_cavalry_tool_handler(tool_name, handler)
            registered += 1
            log.info("Registered Cavalry panel tool handler: %s", tool_name)
        except Exception:
            log.warning(
                "Failed to register Cavalry panel tool handler %s from %s",
                tool_name,
                manifest_path,
                exc_info=True,
            )
    return registered
