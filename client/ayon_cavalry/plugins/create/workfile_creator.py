from ayon_core.pipeline import (
    AutoCreator,
    CreatedInstance,
)
from ayon_cavalry.api import get_stub
from ayon_cavalry.api.pipeline import cache_and_get_instances


class CavalryWorkfileCreator(AutoCreator):
    identifier = "workfile"
    product_base_type = "workfile"
    product_type = product_base_type

    default_variant = "Main"

    def get_instance_attr_defs(self):
        return []

    def collect_instances(self):
        for instance_data in cache_and_get_instances(self):
            creator_id = instance_data.get("creator_identifier")
            if creator_id == self.identifier:
                product_name = instance_data.get("productName", "")
                instance = CreatedInstance(
                    product_base_type=self.product_base_type,
                    product_type=self.product_base_type,
                    product_name=product_name,
                    data=instance_data,
                    creator=self,
                )
                self._add_instance_to_context(instance)

    def update_instances(self, update_list):
        for created_inst, _changes in update_list:
            layer_id = created_inst.get("__layer_id__")
            if layer_id:
                get_stub().imprint(layer_id, created_inst.data_to_store())

    def create(self, options=None):
        existing_instance = None
        for instance in self.create_context.instances:
            if instance.creator_identifier == self.identifier:
                existing_instance = instance
                break

        project_entity = self.create_context.get_current_project_entity()
        folder_entity = self.create_context.get_current_folder_entity()
        task_entity = self.create_context.get_current_task_entity()

        project_name = project_entity["name"]
        folder_path = folder_entity["path"]
        task_name = task_entity["name"]
        host_name = self.create_context.host_name

        existing_folder_path = None
        if existing_instance is not None:
            existing_folder_path = existing_instance.get("folderPath")

        if existing_instance is None:
            product_name = self.get_product_name(
                project_name=project_name,
                project_entity=project_entity,
                folder_entity=folder_entity,
                task_entity=task_entity,
                variant=self.default_variant,
                host_name=host_name,
            )
            data = {
                "folderPath": folder_path,
                "task": task_name,
                "variant": self.default_variant,
            }

            new_instance = CreatedInstance(
                product_base_type=self.product_base_type,
                product_type=self.product_base_type,
                product_name=product_name,
                data=data,
                creator=self,
            )
            self._add_instance_to_context(new_instance)

            stub = get_stub()
            active_comp = stub.get_active_comp()
            comp_id = active_comp.get("id")
            if comp_id:
                store_data = new_instance.data_to_store()
                store_data["__layer_id__"] = comp_id
                stub.imprint(comp_id, store_data)

        elif (
            existing_folder_path != folder_path
            or existing_instance["task"] != task_name
        ):
            product_name = self.get_product_name(
                project_name=project_name,
                project_entity=project_entity,
                folder_entity=folder_entity,
                task_entity=task_entity,
                variant=self.default_variant,
                host_name=host_name,
            )
            existing_instance["folderPath"] = folder_path
            existing_instance["task"] = task_name
            existing_instance["productName"] = product_name
