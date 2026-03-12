"""Load Cavalry Scene Fragment (.cvc) into the active composition."""

from ayon_core.pipeline import get_representation_path
from ayon_core.pipeline.load import LoaderPlugin

from ayon_cavalry.api import get_stub, containerise


def _find_imported_group(stub, before_comp_ids, before_asset_ids):
    """Find the group Cavalry creates when importing a scene fragment.

    Cavalry wraps imported .cvc content in a group (folder). We prefer
    that group for container tracking so the Scene Inventory can manage it.
    Checks both active comp layers and Asset Window layers.
    """
    comp_layers = stub.get_comp_layers(top_level=True)
    asset_layers = stub.get_asset_window_layers(top_level=True)

    comp_after = {l["id"]: l for l in comp_layers}
    asset_after = {l["id"]: l for l in asset_layers}

    new_comp = [
        comp_after[lid] for lid in comp_after
        if lid not in before_comp_ids
    ]
    new_asset = [
        asset_after[lid] for lid in asset_after
        if lid not in before_asset_ids
    ]

    all_new = new_comp + new_asset

    for layer in all_new:
        layer_type = (layer.get("type") or "").lower()
        if "group" in layer_type:
            return layer["id"], [layer["id"]]

    if all_new:
        first = all_new[0]
        return first["id"], [l["id"] for l in all_new]

    return None, []


class SceneFragmentLoader(LoaderPlugin):
    """Load Cavalry Scene Fragment (.cvc) into the active composition.

    Cavalry wraps imported content in a group. We imprint container
    metadata on that group so the Scene Inventory can track it for
    update/remove.
    """

    label = "Load Scene Fragment"
    product_types = {"sceneFragment"}
    representations = {"cvc"}

    def load(self, context, name=None, namespace=None, data=None):
        stub = get_stub()

        path = self.filepath_from_context(context)
        if not path:
            repr_id = context["representation"]["id"]
            self.log.warning(
                "Representation id `%s` is failing to load", repr_id
            )
            return

        path = path.replace("\\", "/")

        folder_name = context["folder"]["name"]
        product_name = context["product"]["name"]
        loaded_item_name = "{}_{}".format(folder_name, product_name)
        namespace = namespace or loaded_item_name

        comp_layers = stub.get_comp_layers(top_level=True)
        asset_layers = stub.get_asset_window_layers(top_level=True)
        before_comp_ids = {l["id"] for l in comp_layers}
        before_asset_ids = {l["id"] for l in asset_layers}

        stub.import_scene(path)

        container_id, members = _find_imported_group(
            stub, before_comp_ids, before_asset_ids
        )

        if not container_id:
            self.log.warning(
                "No new layers detected after import. "
                "The .cvc may be empty or already present."
            )
            return

        containerise(
            name or product_name,
            namespace,
            container_id,
            context,
            self.__class__.__name__,
            members=members,
        )

        return container_id

    def update(self, container, context):
        stub = get_stub()
        members = container.get("members", [])
        repre_entity = context["representation"]
        product_name = context["product"]["name"]
        folder_name = context["folder"]["name"]

        path = get_representation_path(repre_entity)
        if not path:
            self.log.warning("No path for representation")
            return

        path = path.replace("\\", "/")

        for layer_id in members:
            try:
                stub.remove_metadata(layer_id)
                stub.delete_layer(layer_id)
            except Exception as e:
                self.log.debug(
                    "Could not delete layer %s (may already be gone): %s",
                    layer_id,
                    e,
                )

        comp_layers = stub.get_comp_layers(top_level=True)
        asset_layers = stub.get_asset_window_layers(top_level=True)
        before_comp_ids = {l["id"] for l in comp_layers}
        before_asset_ids = {l["id"] for l in asset_layers}

        stub.import_scene(path)

        container_id, new_members = _find_imported_group(
            stub, before_comp_ids, before_asset_ids
        )

        if not container_id:
            self.log.warning("No new layers after re-import")
            return

        loaded_item_name = "{}_{}".format(folder_name, product_name)

        stub.imprint(container_id, {
            "schema": "ayon:container-3.0",
            "id": "ayon:container-3.0",
            "name": product_name,
            "namespace": loaded_item_name,
            "loader": self.__class__.__name__,
            "representation": repre_entity["id"],
            "members": new_members,
        })

    def remove(self, container):
        stub = get_stub()
        members = container.get("members", [])

        for layer_id in members:
            try:
                stub.remove_metadata(layer_id)
                stub.delete_layer(layer_id)
            except Exception as e:
                self.log.warning(
                    "Could not delete layer %s: %s",
                    layer_id,
                    e,
                )
