"""Tests for CavalryServerTool.run_file_script command building."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

if "aiohttp" not in sys.modules:
    _aiohttp = MagicMock()
    _aiohttp.web = MagicMock()
    sys.modules["aiohttp"] = _aiohttp

_COMMUNICATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "client"
    / "ayon_cavalry"
    / "api"
    / "communication.py"
)
_spec = importlib.util.spec_from_file_location(
    "ayon_cavalry_communication",
    _COMMUNICATION_PATH,
)
assert _spec and _spec.loader
_communication = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_communication)
CavalryServerTool = _communication.CavalryServerTool


def _make_tool() -> CavalryServerTool:
    tool = CavalryServerTool.__new__(CavalryServerTool)
    tool.send_command = MagicMock(return_value={"success": True})
    return tool


def test_run_file_script_forwards_path_only():
    tool = _make_tool()
    tool.run_file_script("C:/Scripts/MyAddon/entry.js")

    tool.send_command.assert_called_once_with(
        "run_file_script",
        {"path": "C:/Scripts/MyAddon/entry.js"},
        timeout=120,
    )


def test_run_file_script_forwards_args_path():
    tool = _make_tool()
    tool.run_file_script(
        "C:/Scripts/MyAddon/entry.js",
        args_path="C:/Temp/args.json",
    )

    tool.send_command.assert_called_once_with(
        "run_file_script",
        {
            "path": "C:/Scripts/MyAddon/entry.js",
            "args_path": "C:/Temp/args.json",
        },
        timeout=120,
    )


def test_run_file_script_forwards_payload():
    tool = _make_tool()
    payload = {"template_id": "comp-1", "specs": []}
    tool.run_file_script(
        "C:/Scripts/MyAddon/entry.js",
        payload=payload,
    )

    tool.send_command.assert_called_once_with(
        "run_file_script",
        {
            "path": "C:/Scripts/MyAddon/entry.js",
            "payload": payload,
        },
        timeout=120,
    )


def test_run_file_script_normalizes_backslashes():
    tool = _make_tool()
    tool.run_file_script(
        r"C:\Scripts\MyAddon\entry.js",
        args_path=r"C:\Temp\args.json",
    )

    tool.send_command.assert_called_once_with(
        "run_file_script",
        {
            "path": "C:/Scripts/MyAddon/entry.js",
            "args_path": "C:/Temp/args.json",
        },
        timeout=120,
    )
