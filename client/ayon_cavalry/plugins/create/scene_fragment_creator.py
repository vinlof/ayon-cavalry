"""Create Scene Fragment instances for publishing compositions as .cvc files."""

import os
import re

from ayon_core.lib import BoolDef
from ayon_core.pipeline import (
    Creator,
    CreatedInstance,
    CreatorError,
    AYON_INSTANCE_ID,
    AVALON_INSTANCE_ID,
)
from ayon_core.lib import prepare_template_data
from ayon_core.pipeline.create import PRODUCT_NAME_ALLOWED_SYMBOLS

from ayon_cavalry.api import get_stub
from ayon_cavalry.api.pipeline import cache_and_get_instances


def _get_scene_dir_from_workfile(workfile_path):
    """Return workfile_dir/scene/ for staging .cvc exports."""
    if not workfile_path:
        return None
    workfile_dir = os.path.dirname(workfile_path)
    return os.path.normpath(
        os.path.join(workfile_dir, "scene")
    ).replace("\\", "/")


class SceneFragmentCreator(Creator):
    """Creates 'sceneFragment' instance for publishing compositions as .cvc.

    Exports the composition contents via api.exportSelected to a Cavalry
    Scene Fragment (.cvc) file.
    """

    identifier = "sceneFragment"
    label = "Scene Fragment"
    product_base_type = "sceneFragment"
    product_type = product_base_type
    description = "Export composition as Cavalry Scene Fragment (.cvc)"
    icon = "file-export"
    settings_category = "cavalry"

    create_allow_context_change = True

    def create(self, product_name, data, pre_create_data):
        stub = get_stub()

        ctx = stub.get_create_context()
        workfile_path = ctx.get("scene_path", "")
        if not workfile_path:
            raise CreatorError(
                "Please save workfile via Workfile app first!"
            )
        all_comps = ctx["comps"]
        all_comp_ids = {c["id"] for c in all_comps}

        if pre_create_data.get("use_selection"):
            sel = ctx["selection"]
            comps = [
                item for item in sel
                if item.get("id") in all_comp_ids
            ]
            if not comps:
                comps = [
                    item for item in sel
                    if "comp" in item.get("type", "").lower()
                ]
        else:
            comps = all_comps

        if not comps:
            raise CreatorError(
                "Nothing to create. Select composition(s) if "
                "'Use selection' is toggled, or create at least "
                "one composition."
            )

        scene_dir = _get_scene_dir_from_workfile(workfile_path)
        if scene_dir:
            os.makedirs(scene_dir, exist_ok=True)

        use_composition_name = (
            pre_create_data.get("use_composition_name")
            or len(comps) > 1
        )

        metadata_items = ctx.get("items", [])
        existing_names = {
            inst.get("productName", "")
            for inst in metadata_items
            if inst.get("id") in {AYON_INSTANCE_ID, AVALON_INSTANCE_ID}
            and inst.get("creator_identifier") == self.identifier
        }
        used_names = set(existing_names)

        for comp in comps:
            comp_id = comp["id"]
            comp_name = comp.get("name", "")

            composition_name = re.sub(
                "[^{}]+".format(PRODUCT_NAME_ALLOWED_SYMBOLS),
                "",
                comp_name,
            )

            if use_composition_name:
                if "{composition}" not in product_name.lower():
                    product_name += "{Composition}"

                dynamic_fill = prepare_template_data(
                    {"composition": composition_name}
                )
                comp_product_name = product_name.format(**dynamic_fill)
                data["composition_name"] = composition_name
            else:
                comp_product_name = re.sub(
                    r"\{composition\}",
                    "",
                    product_name,
                    flags=re.IGNORECASE,
                )

            base_name = comp_product_name
            counter = 1
            while comp_product_name in used_names:
                comp_product_name = "{}{}".format(base_name, counter)
                counter += 1
            used_names.add(comp_product_name)

            data["members"] = [comp_id]

            product_type = data.get("productType")
            if not product_type:
                product_type = self.product_base_type

            new_instance = CreatedInstance(
                product_base_type=self.product_base_type,
                product_type=product_type,
                product_name=comp_product_name,
                data=data,
                creator=self,
            )

            store_data = new_instance.data_to_store()
            store_data["__layer_id__"] = comp_id
            stub.imprint(comp_id, store_data)

            self._add_instance_to_context(new_instance)

    def get_pre_create_attr_defs(self):
        return [
            BoolDef(
                "use_selection",
                tooltip=(
                    "Composition for publishable instance should be "
                    "selected by default."
                ),
                default=True,
                label="Use selection",
            ),
            BoolDef(
                "use_composition_name",
                label="Use composition name in product",
            ),
        ]

    def get_instance_attr_defs(self):
        return []

    def collect_instances(self):
        for instance_data in cache_and_get_instances(self):
            creator_id = instance_data.get("creator_identifier")
            if creator_id == self.identifier:
                instance = CreatedInstance.from_existing(
                    instance_data, self
                )
                self._add_instance_to_context(instance)

    def update_instances(self, update_list):
        stub = get_stub()
        for created_inst, _changes in update_list:
            layer_id = created_inst.get("__layer_id__")
            if layer_id:
                stub.imprint(layer_id, created_inst.data_to_store())

    def remove_instances(self, instances):
        stub = get_stub()
        for instance in instances:
            self._remove_instance_from_context(instance)

            layer_id = instance.data.get("__layer_id__")
            if not layer_id and instance.data.get("members"):
                layer_id = instance.data["members"][0]
            if layer_id:
                stub.remove_metadata(layer_id)

    def get_dynamic_data(
        self,
        project_name,
        folder_entity,
        task_entity,
        variant,
        host_name,
        instance=None,
        project_entity=None,
        product_type=None,
    ):
        dynamic_data = {}
        if instance is not None:
            composition_name = instance.get("composition_name")
            if composition_name:
                dynamic_data["composition"] = composition_name
        else:
            dynamic_data["composition"] = "{composition}"
        return dynamic_data
