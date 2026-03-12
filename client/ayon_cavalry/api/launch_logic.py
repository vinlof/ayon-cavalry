"""Launch logic for Cavalry host integration.

Starts the Python HTTP server, launches the Cavalry process, waits for
the Cavalry AYON panel to connect, then runs the Qt event loop for
pipeline tools (Workfiles, Loader, Publisher, etc.).
"""

import os
import sys
import subprocess
import collections
import logging
import traceback

from qtpy import QtCore

from qtpy import QtWidgets

from ayon_core.lib import Logger, env_value_to_bool
from ayon_core.pipeline import install_host, CreatorError
from ayon_core.pipeline.create import CreateContext
from ayon_core.tools.utils import host_tools, get_ayon_qt_app

from .communication import CavalryServerTool
from .lib import apply_settings_to_selected_comps

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


def safe_excepthook(*args):
    traceback.print_exception(*args)


def main(*subprocess_args):
    """Main entrypoint to Cavalry launching, called from pre-launch hook."""
    sys.excepthook = safe_excepthook

    from ayon_cavalry.api import CavalryHost

    host = CavalryHost()
    install_host(host)

    os.environ["AYON_LOG_NO_COLORS"] = "0"
    app = get_ayon_qt_app()
    app.setQuitOnLastWindowClosed(False)

    launcher = CavalryProcessLauncher(subprocess_args)
    launcher.start()

    workfiles_on_launch = env_value_to_bool(
        os.getenv("AYON_CAVALRY_WORKFILES_ON_LAUNCH", "true")
    )

    if workfiles_on_launch:
        save = bool(os.getenv("WORKFILES_SAVE_AS"))
        launcher.execute_in_main_thread(
            lambda: host_tools.show_tool_by_name("workfiles", save=save)
        )

    sys.exit(app.exec_())


def _get_pre_create_data_for_creator(creator_identifier):
    """Return pre_create_data dict for the given creator."""
    base = {
        "use_selection": True,
        "use_composition_name": False,
    }
    if creator_identifier == "render":
        base["render_target"] = "local"
        base["mark_for_review"] = False
    return base


def try_direct_create_from_selection(creator_identifier="render", variant="Main"):
    """Create an instance directly if exactly one composition is selected.

    Args:
        creator_identifier (str): Creator plugin identifier (e.g. "render",
            "sceneFragment"). Default "render".
        variant (str): Product variant name (default "Main").

    Returns:
        bool: True if instance was created, False otherwise (opens Publisher).
    """
    try:
        from ayon_core.pipeline import registered_host

        stub = CavalryServerTool.get_instance()
        if not stub or not stub.is_connected:
            return False

        ctx = stub.get_create_context()
        selection = ctx["selection"]
        comps = ctx["comps"]
        comp_ids = {c["id"] for c in comps}

        # Filter selection to compositions only
        selected_comps = [
            item for item in selection
            if item.get("id") in comp_ids
        ]
        if not selected_comps:
            selected_comps = [
                item for item in selection
                if "comp" in item.get("type", "").lower()
            ]

        if len(selected_comps) != 1:
            return False

        comp = selected_comps[0]
        comp_name = comp.get("name", "composition")
        variant = (variant or "Main").strip() or "Main"

        host = registered_host()
        create_context = CreateContext(host)
        create_context.reset()

        pre_create_data = _get_pre_create_data_for_creator(creator_identifier)

        create_context.create(
            creator_identifier=creator_identifier,
            variant=variant,
            pre_create_data=pre_create_data,
        )

        log.info(
            "Created %s instance for composition: %s",
            creator_identifier,
            comp_name,
        )
        return True

    except CreatorError as e:
        log.warning("Direct create skipped: %s", e)
        return False
    except Exception:
        log.debug("Direct create failed", exc_info=True)
        return False


def _run_apply_settings(frames=True, resolution=True):
    """Apply frame range and resolution from AYON context to selected comps."""
    try:
        success, message = apply_settings_to_selected_comps(
            frames=frames, resolution=resolution
        )
        app = get_ayon_qt_app()
        box = QtWidgets.QMessageBox()
        box.setWindowFlags(
            box.windowFlags() | QtCore.Qt.WindowStaysOnTopHint
        )
        if success:
            box.setIcon(QtWidgets.QMessageBox.Information)
            box.setWindowTitle("AYON")
        else:
            box.setIcon(QtWidgets.QMessageBox.Warning)
            box.setWindowTitle("AYON")
        box.setText(message)
        box.exec_()
    except Exception as e:
        log.warning("Apply settings failed: %s", e, exc_info=True)
        app = get_ayon_qt_app()
        box = QtWidgets.QMessageBox()
        box.setWindowFlags(
            box.windowFlags() | QtCore.Qt.WindowStaysOnTopHint
        )
        box.setIcon(QtWidgets.QMessageBox.Critical)
        box.setWindowTitle("AYON")
        box.setText("Failed to apply settings: {}".format(e))
        box.exec_()


def show_tool_by_name(tool_name, tool_data=None):
    tool_data = tool_data or {}
    kwargs = {}
    if tool_name == "loader":
        kwargs["use_context"] = True
    elif tool_name == "creator":
        creator_id = tool_data.get("creator_identifier")
        variant = tool_data.get("variant", "Main")
        if creator_id and try_direct_create_from_selection(
            creator_identifier=creator_id,
            variant=variant,
        ):
            return
        # AYON has no standalone "creator" tool; Create tab lives in Publisher
        tool_name = "publisher"
        kwargs["tab"] = "create"
    host_tools.show_tool_by_name(tool_name, **kwargs)


class CavalryProcessLauncher(QtCore.QObject):
    """Launches HTTP server, Cavalry process, and runs the event loop."""

    _main_thread_callbacks = collections.deque()

    def __init__(self, subprocess_args):
        super().__init__()
        self._subprocess_args = subprocess_args
        self._log = None
        self._started = False
        self._process = None
        self._server = None

        self._start_timer = QtCore.QTimer()
        self._start_timer.setInterval(100)
        self._start_timer.timeout.connect(self._on_start_timer)

        self._loop_timer = QtCore.QTimer()
        self._loop_timer.setInterval(50)
        self._loop_timer.timeout.connect(self._on_loop_timer)

    @property
    def log(self):
        if self._log is None:
            self._log = Logger.get_logger("cavalry-launcher")
        return self._log

    @classmethod
    def execute_in_main_thread(cls, callback):
        cls._main_thread_callbacks.append(callback)

    def start(self):
        if self._started:
            return
        self.log.info("Starting Cavalry launch sequence")
        self._started = True
        self._start_timer.start()

    def exit(self):
        if self._start_timer.isActive():
            self._start_timer.stop()
        if self._loop_timer.isActive():
            self._loop_timer.stop()

        if self._server is not None:
            self._server.stop()

        if self._process:
            self._process.kill()
            self._process.wait()

        QtCore.QCoreApplication.exit()

    @property
    def is_process_running(self):
        if self._process is not None:
            return self._process.poll() is None
        return False

    @property
    def is_host_connected(self):
        if not self.is_process_running:
            return False
        if self._server and self._server.is_connected:
            return True
        return None

    def _on_start_timer(self):
        # Step 1: Start the HTTP server
        if self._server is None:
            self._init_server()
            return

        if not self._server.is_running:
            return

        # Step 2: Launch Cavalry
        if self._process is None:
            self._start_process()
            self.log.info(
                "Waiting for Cavalry AYON panel to connect..."
            )
            return

        # Step 3: Wait for panel connection
        connected = self.is_host_connected
        if connected:
            self.log.info("Cavalry AYON panel connected!")
            self._start_timer.stop()
            self._loop_timer.start()
        elif connected is False:
            self.exit()

    def _on_loop_timer(self):
        # Process main-thread callbacks
        cls = self.__class__
        for _ in range(len(cls._main_thread_callbacks)):
            if cls._main_thread_callbacks:
                callback = cls._main_thread_callbacks.popleft()
                callback()

        if not self.is_process_running:
            self.log.info("Cavalry process exited. Shutting down.")
            self.exit()
        elif not self._server.is_running:
            self.log.info("HTTP server stopped. Shutting down.")
            self.exit()

    def _init_server(self):
        self.log.debug("Initializing HTTP server for Cavalry communication")

        self._server = CavalryServerTool()

        # Register callback so Cavalry panel buttons open tools on main thread
        self._server.set_tool_callback(self._on_tool_requested)

        # Write config for the Cavalry panel to find us
        scripts_dir = os.path.join(
            os.environ.get("APPDATA", ""),
            "Cavalry", "Scripts", "AYON"
        )
        self._server.write_config_file(scripts_dir)
        self._server.start()

    def _on_tool_requested(self, tool_name, data=None):
        """Called from server thread when Cavalry panel requests a tool."""
        import functools
        data = data or {}
        if tool_name == "set_settings":
            frames = data.get("frames", True)
            resolution = data.get("resolution", True)
            self.log.info("Queueing set_settings: frames=%s resolution=%s", frames, resolution)
            self.execute_in_main_thread(
                functools.partial(
                    _run_apply_settings, frames, resolution
                )
            )
        else:
            self.execute_in_main_thread(
                functools.partial(show_tool_by_name, tool_name, data)
            )

    def _start_process(self):
        if self._process is not None:
            return

        self.log.info("Launching Cavalry: %s", self._subprocess_args)

        environ = os.environ.copy()
        environ["AYON_CAVALRY_PYTHON_PORT"] = str(self._server.python_port)

        try:
            self._process = subprocess.Popen(
                self._subprocess_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=environ,
            )
        except Exception:
            self.log.error("Failed to launch Cavalry", exc_info=True)
            self.exit()
