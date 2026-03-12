import os
import re

from ayon_core.lib import BoolDef, UISeparatorDef, EnumDef
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


def _get_render_dir_from_workfile(workfile_path):
    """Return workfile_dir/render/ for the given workfile path."""
    if not workfile_path:
        return None
    workfile_dir = os.path.dirname(workfile_path)
    return os.path.normpath(
        os.path.join(workfile_dir, "render")
    ).replace("\\", "/")


class RenderCreator(Creator):
    """Creates 'render' instance for publishing.

    Result of 'render' instance is an image sequence or video rendered
    from a Cavalry composition via the Render Queue.
    """

    identifier = "render"
    label = "Render"
    product_base_type = "render"
    product_type = product_base_type
    description = "Render creator"
    icon = "eye"
    settings_category = "cavalry"

    create_allow_context_change = True

    rendering_targets = {
        "local": "Local machine rendering",
        "frames": "Use existing frames",
        "farm": "Render on farm (Deadline)",
    }

    mark_for_review = False
    force_setting_values = False
    rename_comp_to_product_name = True

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

        render_dir = _get_render_dir_from_workfile(workfile_path)
        if render_dir:
            os.makedirs(render_dir, exist_ok=True)

        use_composition_name = (
            pre_create_data.get("use_composition_name")
            or len(comps) > 1
        )

        creator_attributes = {
            "render_target": pre_create_data.get(
                "render_target", "local"
            ),
            "mark_for_review": pre_create_data.get(
                "mark_for_review", self.mark_for_review
            ),
            "format": pre_create_data.get("format", ""),
        }

        # Use metadata from get_create_context (no extra round-trip)
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
            data["creator_attributes"] = creator_attributes

            if self.rename_comp_to_product_name:
                data["orig_comp_name"] = comp_name

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

            # Batch set_comp_settings + rename_layer when applicable
            batch_cmds = []
            if self.force_setting_values:
                if data.get("task"):
                    entity = self.create_context.get_task_entity(
                        folder_path=data["folderPath"],
                        task_name=data["task"],
                    )
                else:
                    entity = self.create_context.get_folder_entity(
                        folder_path=data["folderPath"]
                    )
                if entity:
                    attribs = entity.get("attrib", {})
                    settings = {}
                    if attribs.get("resolutionWidth"):
                        settings["resolution_width"] = attribs["resolutionWidth"]
                    if attribs.get("resolutionHeight"):
                        settings["resolution_height"] = attribs["resolutionHeight"]
                    if attribs.get("fps"):
                        settings["fps"] = attribs["fps"]
                    if attribs.get("frameStart") is not None:
                        settings["frame_start"] = attribs["frameStart"]
                    if attribs.get("frameEnd") is not None:
                        settings["frame_end"] = attribs["frameEnd"]
                    if settings:
                        batch_cmds.append({
                            "command": "set_comp_settings",
                            "args": {"comp_id": comp_id, **settings},
                        })
            if self.rename_comp_to_product_name:
                batch_cmds.append({
                    "command": "rename_layer",
                    "args": {"layer_id": comp_id, "name": comp_product_name},
                })
            if batch_cmds:
                stub.send_commands_batch(batch_cmds)

            rq_item_id = stub.create_rq_item_and_imprint(
                comp_id, store_data, path=render_dir
            )
            new_instance.data["__layer_id__"] = rq_item_id
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
            UISeparatorDef(),
            EnumDef(
                "render_target",
                items=self.rendering_targets,
                label="Render target",
            ),
            EnumDef(
                "format",
                label="Output format (farm)",
                items={
                    "": "Auto-detect from Render Manager",
                    "png": "PNG",
                    "jpeg": "JPEG",
                    "mp4": "MP4",
                    "webm": "WebM",
                    "mov": "QuickTime (MOV)",
                    "svg": "SVG",
                    "gif": "GIF",
                    "webp": "WebP",
                    "apng": "APNG",
                    "audio": "Audio",
                },
                tooltip="Override format for farm renders when auto-detect fails.",
            ),
            BoolDef(
                "mark_for_review",
                label="Review",
                default=self.mark_for_review,
            ),
        ]

    def get_instance_attr_defs(self):
        return [
            EnumDef(
                "render_target",
                items=self.rendering_targets,
                label="Render target",
            ),
            EnumDef(
                "format",
                label="Output format (farm)",
                items={
                    "": "Auto-detect from Render Manager",
                    "png": "PNG",
                    "jpeg": "JPEG",
                    "mp4": "MP4",
                    "webm": "WebM",
                    "mov": "QuickTime (MOV)",
                    "svg": "SVG",
                    "gif": "GIF",
                    "webp": "WebP",
                    "apng": "APNG",
                    "audio": "Audio",
                },
                tooltip="Override format for farm renders when auto-detect fails.",
            ),
            BoolDef(
                "mark_for_review",
                label="Review",
                default=False,
            ),
        ]

    def _apply_settings_from_entity(self, stub, comp_id, entity):
        """Apply fps/resolution/frame range from AYON entity to comp."""
        if not entity:
            return

        attribs = entity.get("attrib", {})
        settings = {}
        if attribs.get("resolutionWidth"):
            settings["resolution_width"] = attribs["resolutionWidth"]
        if attribs.get("resolutionHeight"):
            settings["resolution_height"] = attribs["resolutionHeight"]
        if attribs.get("fps"):
            settings["fps"] = attribs["fps"]
        if attribs.get("frameStart") is not None:
            settings["frame_start"] = attribs["frameStart"]
        if attribs.get("frameEnd") is not None:
            settings["frame_end"] = attribs["frameEnd"]

        if settings:
            stub.set_comp_settings(comp_id=comp_id, **settings)

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
            if not layer_id and created_inst.get("members"):
                layer_id = created_inst["members"][0]
            if layer_id:
                stub.imprint(layer_id, created_inst.data_to_store())

            name_change = _changes.get("productName")
            if self.rename_comp_to_product_name and name_change:
                member_id = created_inst.data.get("members", [None])[0]
                if member_id:
                    stub.rename_layer(member_id, name_change.new_value)

    def remove_instances(self, instances):
        stub = get_stub()
        for instance in instances:
            self._remove_instance_from_context(instance)

            layer_id = instance.get("__layer_id__")
            if not layer_id and instance.data.get("members"):
                layer_id = instance.data["members"][0]
            comp_id = instance.data.get("members", [None])[0]
            if layer_id:
                stub.remove_metadata(layer_id)
                if layer_id != comp_id:
                    stub.delete_layer(layer_id)

            if self.rename_comp_to_product_name and comp_id:
                orig_name = instance.data.get("orig_comp_name")
                if orig_name:
                    stub.rename_layer(comp_id, orig_name)

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
