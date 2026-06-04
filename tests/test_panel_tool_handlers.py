"""Tests for loading Cavalry panel tool handlers from manifest."""

from __future__ import annotations

import json
from pathlib import Path

from ayon_cavalry.api.panel_tool_handlers import load_panel_tool_handlers_from_manifest
from ayon_cavalry.api.panel_tool_registry import (
    get_cavalry_tool_handler,
    unregister_cavalry_tool_handler,
)


def test_load_panel_tool_handlers_from_manifest(tmp_path):
    def _dummy_handler(_data):
        return None

    manifest = {
        "handlers": [
            {
                "tool": "test_panel_tool",
                "module": __name__,
                "callable": "_dummy_handler",
            }
        ]
    }
    manifest_path = tmp_path / "ayon_panel_tool_handlers.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    try:
        count = load_panel_tool_handlers_from_manifest(str(tmp_path))
        assert count == 1
        assert get_cavalry_tool_handler("test_panel_tool") is _dummy_handler
    finally:
        unregister_cavalry_tool_handler("test_panel_tool")
