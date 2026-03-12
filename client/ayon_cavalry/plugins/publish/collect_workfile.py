import os

import pyblish.api


class CollectWorkfile(pyblish.api.InstancePlugin):
    """Collect Workfile representation."""

    label = "Collect Cavalry Workfile"
    order = pyblish.api.CollectorOrder + 0.1
    families = ["workfile"]
    hosts = ["cavalry"]

    def process(self, instance):
        current_file = instance.context.data["currentFile"]
        staging_dir = os.path.dirname(current_file)
        scene_file = os.path.basename(current_file)

        instance.data.setdefault("representations", []).append({
            "name": "cv",
            "ext": "cv",
            "files": scene_file,
            "stagingDir": staging_dir,
        })
