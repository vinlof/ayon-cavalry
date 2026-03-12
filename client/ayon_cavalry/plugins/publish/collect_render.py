"""Collect render instances from the Cavalry scene.

Gathers composition info (fps, resolution, frame range) and prepares
render instances for extraction.
"""

import pyblish.api

from ayon_cavalry.api import get_stub


class CollectCavalryRender(pyblish.api.InstancePlugin):
    """Prepare render instance data from Cavalry compositions.

    Must run after collect_review but before extraction.
    """

    order = pyblish.api.CollectorOrder + 0.125
    label = "Collect Cavalry Render Layers"
    hosts = ["cavalry"]
    families = ["render"]

    def process(self, instance):
        stub = get_stub()

        if not instance.data.get("active", True):
            return

        members = instance.data.get("members", [])
        if not members:
            self.log.warning("Render instance has no composition members")
            return

        comp_id = members[0]

        comp_settings = stub.get_comp_settings(comp_id)
        if not comp_settings or not comp_settings.get("success"):
            self.log.warning(
                "Could not get comp settings for %s", comp_id
            )
            return

        frame_start = comp_settings.get("frame_start", 0)
        frame_end = comp_settings.get("frame_end", 100)
        fps = comp_settings.get("fps", 25)
        res_width = comp_settings.get("resolution_width", 1920)
        res_height = comp_settings.get("resolution_height", 1080)

        instance.data["frameStart"] = frame_start
        instance.data["frameEnd"] = frame_end
        instance.data["fps"] = fps
        instance.data["resolutionWidth"] = res_width
        instance.data["resolutionHeight"] = res_height
        instance.data["pixelAspect"] = 1

        handle_start = instance.data.get("handleStart", 0)
        handle_end = instance.data.get("handleEnd", 0)
        instance.data["frameStartHandle"] = frame_start - handle_start
        instance.data["frameEndHandle"] = frame_end + handle_end

        instance.data["comp_id"] = comp_id
        instance.data["comp_name"] = comp_settings.get("name", "")

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
            "Collected render: %s (%s) frames %d-%d @ %sfps %dx%d",
            instance.data.get("productName", ""),
            comp_id,
            frame_start,
            frame_end,
            fps,
            res_width,
            res_height,
        )
