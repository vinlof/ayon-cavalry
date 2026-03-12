"""Load files (images, sequences, scenes) into Cavalry.

Stores the imported product version as a container tracked by AYON
using Cavalry's userData mechanism.
"""

import os
import time

from ayon_core.pipeline import get_representation_path
from ayon_core.pipeline.load import LoaderPlugin

from ayon_cavalry.api import get_stub, containerise


class FileLoader(LoaderPlugin):
    """Load images, footage, and Cavalry scenes.

    Stores the imported product version in a container tracked by AYON.
    """

    label = "Load file"

    product_base_types = {
        "image",
        "plate",
        "render",
        "prerender",
        "review",
        "workfile",
    }
    product_types = product_base_types
    representations = {"*"}

    def load(self, context, name=None, namespace=None, data=None):
        stub = get_stub()
        loaded_item_name = "{}_{}".format(
            context["folder"]["name"], name
        )
        loaded_item_name = self._get_unique_name(stub, loaded_item_name)

        path = self.filepath_from_context(context)
        if not path:
            repr_id = context["representation"]["id"]
            self.log.warning(
                "Representation id `%s` is failing to load", repr_id
            )
            return

        path = path.replace("\\", "/")

        is_sequence = len(context["representation"].get("files", [])) > 1
        ext = os.path.splitext(path)[1].lower()

        if ext in (".cv", ".cvc"):
            stub.import_scene(path)
            asset_id = ""
            footage_id, offset = "", 0
        else:
            asset_id = stub.load_asset(path, is_sequence)
            footage_id, offset = "", 0
            if asset_id:
                footage_id, offset = stub.add_asset_to_comp(asset_id)

        container_id = asset_id or loaded_item_name
        namespace = namespace or loaded_item_name

        result = containerise(
            name,
            namespace,
            container_id,
            context,
            self.__class__.__name__,
        )

        if footage_id and offset != 0:
            time.sleep(0.1)
            stub.offset_layer_time(footage_id, offset)

        return result

    def update(self, container, context):
        stub = get_stub()
        layer_id = container.get("members", [None])[0]
        repre_entity = context["representation"]
        product_name = context["product"]["name"]
        folder_name = context["folder"]["name"]

        path = get_representation_path(repre_entity)
        if not path:
            self.log.warning("No path for representation")
            return

        path = path.replace("\\", "/")

        if layer_id:
            try:
                stub.replace_asset(layer_id, path)
            except Exception:
                self.log.warning(
                    "Could not replace asset %s, loading new", layer_id
                )

        loaded_item_name = "{}_{}".format(folder_name, product_name)
        stub.imprint(layer_id, {
            "schema": "ayon:container-3.0",
            "id": "ayon:container-3.0",
            "name": product_name,
            "namespace": loaded_item_name,
            "loader": self.__class__.__name__,
            "representation": repre_entity["id"],
            "members": [layer_id],
        })

    def remove(self, container):
        stub = get_stub()
        layer_id = container.get("members", [None])[0]
        if layer_id:
            stub.remove_metadata(layer_id)
            try:
                stub.delete_layer(layer_id)
            except Exception:
                self.log.warning(
                    "Could not delete layer %s", layer_id
                )

    def _get_unique_name(self, stub, name):
        """Ensure loaded item name is unique in the asset window."""
        existing = stub.get_asset_window_layers()
        existing_names = {item.get("name", "") for item in existing}

        if name not in existing_names:
            return name

        counter = 1
        while True:
            candidate = "{}_{}".format(name, str(counter).zfill(3))
            if candidate not in existing_names:
                return candidate
            counter += 1
