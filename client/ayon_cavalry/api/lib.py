"""Utility functions for the Cavalry AYON addon."""

import logging

from ayon_core.pipeline.context_tools import (
    get_current_task_entity,
    get_current_folder_entity,
)

from .communication import CavalryServerTool

log = logging.getLogger(__name__)


def apply_settings_to_selected_comps(frames=True, resolution=True):
    """Apply frame range and/or resolution from AYON context to selected comps.

    Args:
        frames (bool): Apply frame range and fps from task/folder attributes.
        resolution (bool): Apply resolution from task/folder attributes.

    Returns:
        tuple: (success: bool, message: str)
    """
    stub = CavalryServerTool.get_instance()
    if not stub or not stub.is_connected:
        return False, "Cavalry panel is not connected."

    entity = get_current_task_entity()
    if not entity:
        entity = get_current_folder_entity()
    if not entity:
        return False, "No folder or task in context. Open a workfile first."

    attribs = entity.get("attrib", {})
    if not attribs:
        return False, "No attributes on folder/task."

    ctx = stub.get_create_context()
    comp_ids = {c["id"] for c in ctx.get("comps", [])}
    selection = ctx.get("selection", [])

    selected_comps = [
        item for item in selection
        if item.get("id") in comp_ids
    ]
    if not selected_comps:
        selected_comps = [
            item for item in selection
            if "comp" in item.get("type", "").lower()
        ]
    if not selected_comps:
        return False, "Select at least one composition."

    settings = {}
    if frames:
        if attribs.get("frameStart") is not None:
            settings["frame_start"] = attribs["frameStart"]
        if attribs.get("frameEnd") is not None:
            settings["frame_end"] = attribs["frameEnd"]
        if attribs.get("fps"):
            settings["fps"] = attribs["fps"]
    if resolution:
        if attribs.get("resolutionWidth"):
            settings["resolution_width"] = attribs["resolutionWidth"]
        if attribs.get("resolutionHeight"):
            settings["resolution_height"] = attribs["resolutionHeight"]

    if not settings:
        return False, "No frame or resolution attributes on task."

    for comp in selected_comps:
        comp_id = comp.get("id")
        if comp_id:
            stub.set_comp_settings(comp_id=comp_id, **settings)
            log.info("Applied settings to %s: %s", comp.get("name", comp_id), settings)

    count = len(selected_comps)
    return True, f"Applied to {count} composition(s)."


def get_stub():
    """Get the CavalryServerTool singleton.

    Returns:
        CavalryServerTool: The server communication tool instance.

    Raises:
        ConnectionError: If the server is not running or Cavalry is
            not connected.
    """
    server = CavalryServerTool.get_instance()
    if server is None:
        raise ConnectionError(
            "CavalryServerTool has not been initialized yet."
        )
    if not server.is_connected:
        raise ConnectionError(
            "Cavalry panel is not connected. Open the AYON panel in"
            " Cavalry via Window > Scripts > AYON."
        )
    return server
