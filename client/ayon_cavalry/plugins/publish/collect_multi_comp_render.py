"""Collect multi-comp render instances from the Cavalry scene.

Gathers composition info for each comp (fps, resolution, frame range)
and prepares multi-comp render instances for extraction.
"""

import pyblish.api

from ayon_cavalry.api import get_stub


class CollectMultiCompRender(pyblish.api.InstancePlugin):
    """Prepare multi-comp render instance data from Cavalry compositions.

    Runs when instance has multiple members (len(members) > 1).
    Uses union of frame ranges and stores per-comp settings for extractor.
    """

    order = pyblish.api.CollectorOrder + 0.13
    label = "Collect Multi-Comp Render"
    hosts = ["cavalry"]
    families = ["render"]

    def process(self, instance):
        stub = get_stub()

        if not instance.data.get("active", True):
            return

        members = instance.data.get("members", [])
        if len(members) <= 1:
            return

        comp_settings_map = {}
        frame_starts = []
        frame_ends = []
        fps_list = []
        res_widths = []
        res_heights = []

        for comp_id in members:
            comp_settings = stub.get_comp_settings(comp_id)
            if not comp_settings:
                self.log.warning(
                    "Could not get comp settings for %s", comp_id
                )
                continue

            comp_settings_map[comp_id] = {
                "frame_start": comp_settings.get("frame_start", 0),
                "frame_end": comp_settings.get("frame_end", 100),
                "fps": comp_settings.get("fps", 25),
                "resolution_width": comp_settings.get(
                    "resolution_width", 1920
                ),
                "resolution_height": comp_settings.get(
                    "resolution_height", 1080
                ),
                "name": comp_settings.get("name", ""),
            }

            frame_starts.append(comp_settings_map[comp_id]["frame_start"])
            frame_ends.append(comp_settings_map[comp_id]["frame_end"])
            fps_list.append(comp_settings_map[comp_id]["fps"])
            res_widths.append(comp_settings_map[comp_id]["resolution_width"])
            res_heights.append(comp_settings_map[comp_id]["resolution_height"])

        if not comp_settings_map:
            self.log.warning("No valid comp settings for multi-comp instance")
            return

        instance.data["comp_settings"] = comp_settings_map
        instance.data["frameStart"] = min(frame_starts)
        instance.data["frameEnd"] = max(frame_ends)
        instance.data["fps"] = fps_list[0] if fps_list else 25
        instance.data["resolutionWidth"] = res_widths[0] if res_widths else 1920
        instance.data["resolutionHeight"] = res_heights[0] if res_heights else 1080
        instance.data["pixelAspect"] = 1

        handle_start = instance.data.get("handleStart", 0)
        handle_end = instance.data.get("handleEnd", 0)
        instance.data["frameStartHandle"] = (
            instance.data["frameStart"] - handle_start
        )
        instance.data["frameEndHandle"] = (
            instance.data["frameEnd"] + handle_end
        )

        current_file = instance.context.data.get("currentFile", "")
        instance.data["source"] = current_file

        creator_attributes = instance.data.get("creator_attributes", {})
        render_target = creator_attributes.get("render_target", "local")

        if render_target == "local":
            if "render.local" not in instance.data.get("families", []):
                instance.data.setdefault("families", []).append(
                    "render.local"
                )
        elif render_target == "frames":
            if "render.frames" not in instance.data.get("families", []):
                instance.data.setdefault("families", []).append(
                    "render.frames"
                )
        elif render_target == "farm":
            if "render.farm" not in instance.data.get("families", []):
                instance.data.setdefault("families", []).append(
                    "render.farm"
                )
            instance.data["farm"] = True
            families = instance.data.get("families", [])
            if "review" in families:
                families.remove("review")

        self.log.info(
            "Collected multi-comp render: %s (%d comps) frames %d-%d",
            instance.data.get("productName", ""),
            len(members),
            instance.data["frameStart"],
            instance.data["frameEnd"],
        )
