import os

import pyblish.api

from ayon_cavalry.api import get_stub


class CollectCurrentFile(pyblish.api.ContextPlugin):
    """Inject the current working file into context."""

    order = pyblish.api.CollectorOrder - 0.49
    label = "Current File"
    hosts = ["cavalry"]

    def process(self, context):
        current_file = get_stub().get_active_document_full_name()
        if current_file:
            current_file = os.path.normpath(current_file).replace("\\", "/")
        context.data["currentFile"] = current_file or ""
