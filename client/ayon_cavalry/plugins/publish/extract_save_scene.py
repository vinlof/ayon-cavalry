import pyblish.api

from ayon_core.pipeline import publish
from ayon_cavalry.api import get_stub


class ExtractSaveScene(pyblish.api.ContextPlugin):
    """Save scene before extraction."""

    order = publish.Extractor.order - 0.48
    label = "Extract Save Scene"
    hosts = ["cavalry"]

    def process(self, context):
        stub = get_stub()
        stub.save()
