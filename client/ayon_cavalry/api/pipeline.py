"""Cavalry host integration for AYON pipeline.

Contains the CavalryHost class, container management, and instance caching.
"""

import os
import logging

from qtpy import QtWidgets

import pyblish.api

from ayon_core.lib import Logger, register_event_callback
from ayon_core.pipeline import (
    register_loader_plugin_path,
    register_creator_plugin_path,
    AYON_CONTAINER_ID,
    AVALON_INSTANCE_ID,
    AYON_INSTANCE_ID,
)
from ayon_core.pipeline.load import any_outdated_containers
from ayon_core.host import (
    HostBase,
    IWorkfileHost,
    ILoadHost,
    IPublishHost,
)
from ayon_core.tools.utils import get_ayon_qt_app

from ayon_cavalry import CAVALRY_ADDON_ROOT
from .lib import get_stub
from .communication import CavalryServerTool

log = logging.getLogger(__name__)

PLUGINS_DIR = os.path.join(CAVALRY_ADDON_ROOT, "plugins")
PUBLISH_PATH = os.path.join(PLUGINS_DIR, "publish")
LOAD_PATH = os.path.join(PLUGINS_DIR, "load")
CREATE_PATH = os.path.join(PLUGINS_DIR, "create")


class CavalryHost(HostBase, IWorkfileHost, ILoadHost, IPublishHost):
    """AYON host implementation for Cavalry."""

    name = "cavalry"

    def __init__(self):
        self._stub = None
        super().__init__()

    @property
    def stub(self):
        if self._stub:
            return self._stub

        try:
            stub = get_stub()
        except ConnectionError:
            log.debug("Not connected yet, ignoring")
            return None

        self._stub = stub
        return self._stub

    def install(self):
        log.info("Installing Cavalry host integration")

        pyblish.api.register_host("cavalry")
        pyblish.api.register_plugin_path(PUBLISH_PATH)

        if os.path.isdir(LOAD_PATH):
            register_loader_plugin_path(LOAD_PATH)
        if os.path.isdir(CREATE_PATH):
            register_creator_plugin_path(CREATE_PATH)

        register_event_callback("application.launched", application_launch)

    # -- IWorkfileHost --

    def get_workfile_extensions(self):
        return [".cv"]

    def open_workfile(self, filepath):
        filepath = filepath.replace("\\", "/")
        log.info("Opening workfile: %s", filepath)
        server = get_stub()
        result = server.send_command("open_scene", {"path": filepath})
        opened_path = result.get("path", filepath)
        log.info("Workfile opened: %s", opened_path)
        return opened_path

    def save_workfile(self, filepath=None):
        server = get_stub()
        if filepath:
            filepath = filepath.replace("\\", "/")
            log.info("Saving workfile as: %s", filepath)
            result = server.send_command(
                "save_scene_as", {"path": filepath}
            )
        else:
            log.info("Saving current workfile")
            result = server.send_command("save_scene")

        saved_path = result.get("path", filepath or "")
        log.info("Workfile saved: %s", saved_path)
        return saved_path

    def get_current_workfile(self):
        server = CavalryServerTool.get_instance()
        if server is None or not server.is_connected:
            return ""

        cached = server.current_scene_path
        if cached:
            return cached

        try:
            result = server.send_command("get_scene_path", timeout=5)
            return result.get("path", "")
        except (ConnectionError, TimeoutError):
            return ""

    def work_root(self, session):
        return session.get("AYON_WORKDIR", "")

    def workfile_has_unsaved_changes(self):
        server = CavalryServerTool.get_instance()
        if server is None or not server.is_connected:
            return False
        try:
            result = server.send_command("has_unsaved_changes", timeout=5)
            return result.get("unsaved", False)
        except (ConnectionError, TimeoutError):
            return False

    # -- ILoadHost --

    def get_containers(self):
        return ls()

    # -- IPublishHost --

    def get_context_data(self):
        stub = self.stub
        if not stub:
            return {}
        meta = stub.get_metadata()
        for item in meta:
            if item.get("id") == "publish_context":
                item.pop("id")
                return item
        return {}

    def update_context_data(self, data, changes):
        stub = self.stub
        if not stub:
            return
        item = dict(data)
        item["id"] = "publish_context"
        active_comp = stub.get_active_comp()
        comp_id = active_comp.get("id")
        if comp_id:
            stub.imprint(comp_id, item, key="ayon_context")

    def list_instances(self):
        stub = self.stub
        if not stub:
            log.debug("list_instances: no stub (Cavalry panel not connected)")
            return []

        instances = []
        layers_meta = stub.get_metadata()
        log.debug(
            "list_instances: get_metadata returned %d items",
            len(layers_meta),
        )
        for instance in layers_meta:
            inst_id = instance.get("id")
            if inst_id in {AYON_INSTANCE_ID, AVALON_INSTANCE_ID}:
                instances.append(instance)
            elif inst_id:
                log.debug(
                    "list_instances: skipping item id=%r layer=%s",
                    inst_id,
                    instance.get("__layer_id__", "?"),
                )
        log.debug("list_instances: returning %d creator instances", len(instances))
        return instances

    def remove_instance(self, instance):
        stub = self.stub
        if not stub:
            return

        inst_id = instance.get("instance_id")
        if not inst_id:
            log.warning("No instance identifier for %s", instance)
            return

        layer_id = instance.get("__layer_id__")
        if layer_id:
            stub.remove_metadata(layer_id)


def application_launch():
    """Triggered after start of app."""
    check_inventory()


def ls():
    """Yield containers from the active Cavalry scene.

    Yields:
        dict: Container data including objectName and layer reference.
    """
    try:
        stub = get_stub()
    except ConnectionError:
        log.debug("Not connected yet, ignoring")
        return

    layers_meta = stub.get_metadata()
    for item in layers_meta:
        if not item:
            continue
        if "container" not in item.get("id", ""):
            continue

        item["objectName"] = item.get("name", "")
        yield item


def check_inventory():
    """Check loaded containers for outdated versions."""
    if not any_outdated_containers():
        return

    _app = get_ayon_qt_app()
    message_box = QtWidgets.QMessageBox()
    message_box.setIcon(QtWidgets.QMessageBox.Warning)
    message_box.setText("There are outdated containers in the scene.")
    message_box.exec_()


def containerise(name, namespace, layer_id, context, loader=None, members=None):
    """Create a container entry on a Cavalry layer.

    Args:
        name (str): Product name.
        namespace (str): Container namespace.
        layer_id (str): Cavalry layer/asset ID to store container on.
        context (dict): Representation context from loader.
        loader (str, optional): Loader class name.
        members (list, optional): Layer IDs that belong to this container.
            If None, uses [layer_id]. Use for multi-member containers
            (e.g. scene fragments with multiple imported layers).

    Returns:
        str: The layer_id that was containerised.
    """
    data = {
        "schema": "ayon:container-3.0",
        "id": AYON_CONTAINER_ID,
        "name": name,
        "namespace": namespace,
        "loader": str(loader),
        "representation": context["representation"]["id"],
        "members": members if members is not None else [layer_id],
    }

    stub = get_stub()
    stub.imprint(layer_id, data)
    return layer_id


def cache_and_get_instances(creator):
    """Cache instances in shared data.

    Args:
        creator (Creator): Plugin which would like to get instances from host.

    Returns:
        list[dict]: All instances stored in metadata.
    """
    shared_key = "ayon.cavalry.instances"
    if shared_key not in creator.collection_shared_data:
        creator.collection_shared_data[shared_key] = (
            creator.host.list_instances()
        )
    return creator.collection_shared_data[shared_key]
