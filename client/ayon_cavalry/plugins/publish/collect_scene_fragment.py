"""Collect Scene Fragment instances for publishing as .cvc files."""

import pyblish.api

from ayon_cavalry.api import get_stub


class CollectSceneFragment(pyblish.api.InstancePlugin):
    """Prepare sceneFragment instance data for extraction."""

    order = pyblish.api.CollectorOrder + 0.12
    label = "Collect Scene Fragment"
    hosts = ["cavalry"]
    families = ["sceneFragment"]

    def process(self, instance):
        if not instance.data.get("active", True):
            return

        members = instance.data.get("members", [])
        if not members:
            self.log.warning("Scene fragment instance has no composition members")
            return

        comp_id = members[0]
        stub = get_stub()

        comp_settings = stub.get_comp_settings(comp_id)
        if comp_settings:
            instance.data["comp_name"] = comp_settings.get("name", "")

        instance.data["comp_id"] = comp_id

        current_file = instance.context.data.get("currentFile", "")
        instance.data["source"] = current_file

        self.log.info(
            "Collected scene fragment: %s (comp: %s)",
            instance.data.get("productName", ""),
            comp_id,
        )
