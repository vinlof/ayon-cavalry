"""Extract Scene Fragment by exporting composition to .cvc file."""

import os

from ayon_core.pipeline import publish

from ayon_cavalry.api import get_stub


class ExtractSceneFragment(publish.Extractor):
    """Export composition to .cvc Scene Fragment, preserving name and settings.

    Selects the composition itself (not its contents) before exportSelected,
    matching Cavalry's File > Export Selected behavior.
    """

    order = publish.Extractor.order - 0.46
    label = "Extract Scene Fragment"
    hosts = ["cavalry"]
    families = ["sceneFragment"]

    def process(self, instance):
        stub = get_stub()

        comp_id = instance.data.get("comp_id")
        if not comp_id:
            members = instance.data.get("members", [])
            comp_id = members[0] if members else None

        if not comp_id:
            self.log.warning("No composition to export")
            instance.data["representations"] = []
            return

        product_name = instance.data.get("productName", "sceneFragment")
        staging_dir = self._get_staging_dir(instance)
        os.makedirs(staging_dir, exist_ok=True)

        filename = "{}.cvc".format(product_name)
        path = os.path.join(staging_dir, filename).replace("\\", "/")

        # Select the composition itself (not its contents) so exportSelected
        # preserves the composition name, settings, and structure - matching
        # Cavalry's File > Export Selected behavior.
        stub.select([comp_id])

        success = stub.export_selected(path)
        if not success:
            self.log.error("Failed to export scene fragment to %s", path)
            instance.data["representations"] = []
            return

        if not os.path.isfile(path):
            self.log.error("Export reported success but file not found: %s", path)
            instance.data["representations"] = []
            return

        self.log.info("Exported scene fragment to %s", path)

        instance.data["stagingDir"] = staging_dir
        instance.data["representations"] = [
            {
                "name": "cvc",
                "ext": "cvc",
                "files": filename,
                "stagingDir": staging_dir,
            }
        ]

    def _get_staging_dir(self, instance):
        """Get staging directory for the .cvc export."""
        current_file = instance.context.data.get("currentFile", "")
        if current_file:
            workfile_dir = os.path.dirname(current_file)
            return os.path.normpath(
                os.path.join(workfile_dir, "scene")
            ).replace("\\", "/")

        try:
            staging = instance.data.get("stagingDir")
            if staging:
                return staging
        except KeyError:
            pass

        return os.path.join(
            os.path.expanduser("~"),
            "temp",
            "cavalry_scene",
        ).replace("\\", "/")
