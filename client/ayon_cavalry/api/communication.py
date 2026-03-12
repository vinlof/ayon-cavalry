"""HTTP-based communication server for Cavalry host integration.

Cavalry does not support WebSockets but provides WebClient (HTTP client) and
WebServer (simple HTTP server with POST callbacks) in its JavaScript API.

Architecture:
    Python side: aiohttp HTTP server receives results/heartbeats from Cavalry.
    Cavalry side: built-in WebServer receives commands from Python via POST.

    Python --POST command--> Cavalry WebServer (port AYON_CAVALRY_WEBSERVER_PORT)
    Cavalry --POST result--> Python HTTP server (port AYON_CAVALRY_PYTHON_PORT)
"""

import os
import json
import time
import uuid
import socket
import logging
import threading
import asyncio
import urllib.request
import urllib.error

from aiohttp import web

log = logging.getLogger(__name__)

_TIMING_ENABLED = os.environ.get("AYON_CAVALRY_TIMING", "0").lower() not in (
    "0", "false", "no", "off"
)


def _log_timing(msg, *args, **kwargs):
    """Log timing info when AYON_CAVALRY_TIMING env var is set."""
    if _TIMING_ENABLED:
        log.info("[TIMING] " + msg, *args, **kwargs)


@web.middleware
async def _timing_middleware(request, handler):
    """Log request timing for Python HTTP server (Cavalry -> Python)."""
    t0 = time.perf_counter()
    response = await handler(request)
    if _TIMING_ENABLED:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        path = request.path
        _log_timing("Python HTTP %s %s: %.0fms", request.method, path, elapsed_ms)
    return response


class CavalryServerTool:
    """HTTP server that receives results and heartbeats from Cavalry.

    Also handles sending commands to Cavalry's WebServer.
    """

    _instance = None

    def __init__(self):
        CavalryServerTool._instance = self

        self._python_port = int(
            os.getenv("AYON_CAVALRY_PYTHON_PORT", "8098")
        )
        self._cavalry_port = None

        self._connected = False
        self._last_heartbeat = 0.0
        self._current_scene_path = ""

        self._pending_results = {}
        self._result_events = {}
        self._lock = threading.Lock()

        self._on_tool_request = None

        self._app = web.Application(
            middlewares=[_timing_middleware]
        )
        self._app.router.add_post("/ready", self._handle_ready)
        self._app.router.add_post("/result", self._handle_result)
        self._app.router.add_post("/heartbeat", self._handle_heartbeat)
        self._app.router.add_post("/tool", self._handle_tool)
        self._app.router.add_get("/health", self._handle_health)

        self._server_thread = None

    @staticmethod
    def get_instance():
        return CavalryServerTool._instance

    @property
    def is_connected(self):
        """Check if Cavalry panel has connected.

        For the MVP we rely on the /ready POST and process monitoring
        rather than heartbeat-based liveness. The heartbeat timeout is
        generous because Cavalry's WebServer callback only fires when
        it receives a POST (no idle polling).
        """
        return self._connected

    @property
    def python_port(self):
        return self._python_port

    @property
    def cavalry_port(self):
        return self._cavalry_port

    @property
    def current_scene_path(self):
        return self._current_scene_path

    def find_available_port(self):
        """Find an available port starting from the configured one."""
        port = self._python_port
        for offset in range(12):
            candidate = port + offset
            if not self._port_occupied(candidate):
                self._python_port = candidate
                return candidate
        log.error("Could not find available port in range %d-%d",
                  port, port + 11)
        return None

    def _port_occupied(self, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            return sock.connect_ex(("localhost", port)) == 0

    def start(self):
        """Start the HTTP server in a background thread."""
        port = self.find_available_port()
        if port is None:
            raise RuntimeError("No available port for Python HTTP server")

        self._server_thread = _ServerThread(self._app, port)
        self._server_thread.start()
        log.info("Python HTTP server starting on localhost:%d", port)

    def stop(self):
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.stop()
            log.info("Python HTTP server stopped")

    @property
    def is_running(self):
        if self._server_thread is None:
            return False
        return self._server_thread.is_running

    def write_config_file(self, config_dir):
        """Write connection config JSON for the Cavalry panel to read.

        Args:
            config_dir (str): Directory to write ayon_config.json into.
        """
        config = {
            "python_port": self._python_port,
            "timing": _TIMING_ENABLED,
        }
        os.makedirs(config_dir, exist_ok=True)
        config_path = os.path.join(config_dir, "ayon_config.json")
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        log.info("Wrote connection config to %s", config_path)
        return config_path

    def send_command(self, command, args=None, timeout=30):
        """Send a command to Cavalry and wait for the result.

        Python POSTs the command to Cavalry's WebServer. Cavalry processes
        it and POSTs the result back to our /result endpoint.

        Args:
            command (str): Command name (e.g. "open_scene").
            args (dict): Command arguments.
            timeout (float): Seconds to wait for result.

        Returns:
            dict: Result from Cavalry.

        Raises:
            ConnectionError: If Cavalry is not connected.
            TimeoutError: If no result within timeout.
        """
        if not self._connected or self._cavalry_port is None:
            raise ConnectionError(
                "Cavalry panel is not connected. Open the AYON panel in"
                " Cavalry via Window > Scripts > AYON."
            )

        cmd_id = str(uuid.uuid4())
        event = threading.Event()

        with self._lock:
            self._result_events[cmd_id] = event

        payload = json.dumps({
            "id": cmd_id,
            "command": command,
            "args": args or {},
        })

        t0 = time.perf_counter()
        url = "http://localhost:{}/post".format(self._cavalry_port)
        try:
            req = urllib.request.Request(
                url,
                data=payload.encode("utf-8"),
                headers={"Content-Type": "text/plain"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.URLError as exc:
            with self._lock:
                self._result_events.pop(cmd_id, None)
            raise ConnectionError(
                "Failed to send command to Cavalry: {}".format(exc)
            )
        t_post = time.perf_counter()

        if not event.wait(timeout=timeout):
            with self._lock:
                self._result_events.pop(cmd_id, None)
            _log_timing(
                "send_command %s: POST %.0fms, wait TIMEOUT",
                command, (t_post - t0) * 1000
            )
            raise TimeoutError(
                "Command '{}' timed out after {}s".format(command, timeout)
            )

        t_wait = time.perf_counter()
        with self._lock:
            result = self._pending_results.pop(cmd_id, {})
            self._result_events.pop(cmd_id, None)

        t_total = (time.perf_counter() - t0) * 1000
        _log_timing(
            "send_command %s: POST %.0fms, wait %.0fms, total %.0fms",
            command,
            (t_post - t0) * 1000,
            (t_wait - t_post) * 1000,
            t_total,
        )
        return result

    def send_commands_batch(self, commands, timeout=60):
        """Send multiple commands in one round-trip.

        Args:
            commands (list): Each item is {"command": str, "args": dict}.
            timeout (float): Seconds to wait for result.

        Returns:
            list: Results in same order as commands.
        """
        if not commands:
            return []
        args = {"commands": commands}
        result = self.send_command("batch", args=args, timeout=timeout)
        return result.get("results", [])

    async def _handle_ready(self, request):
        """Cavalry panel reports it's ready and provides its WebServer port."""
        try:
            data = await request.json()
        except Exception:
            body = await request.text()
            data = json.loads(body) if body else {}

        self._cavalry_port = data.get("cavalry_port")
        self._current_scene_path = data.get("scene_path", "")
        self._connected = True
        self._last_heartbeat = time.time()

        log.info(
            "Cavalry panel connected (cavalry port: %s, scene: %s)",
            self._cavalry_port,
            self._current_scene_path,
        )
        return web.json_response({"status": "ok"})

    async def _handle_result(self, request):
        """Cavalry posts a command result."""
        try:
            data = await request.json()
        except Exception:
            body = await request.text()
            data = json.loads(body) if body else {}

        cmd_id = data.get("id")
        result = data.get("result", {})

        if cmd_id:
            with self._lock:
                self._pending_results[cmd_id] = result
                event = self._result_events.get(cmd_id)
                if event:
                    event.set()

        return web.json_response({"status": "ok"})

    async def _handle_heartbeat(self, request):
        """Cavalry sends periodic heartbeats with scene info."""
        try:
            data = await request.json()
        except Exception:
            body = await request.text()
            data = json.loads(body) if body else {}

        self._last_heartbeat = time.time()
        self._connected = True
        scene_path = data.get("scene_path", "")
        if scene_path:
            self._current_scene_path = scene_path

        return web.json_response({"status": "ok"})

    async def _handle_tool(self, request):
        """Cavalry panel requests a pipeline tool to be opened."""
        try:
            data = await request.json()
        except Exception:
            body = await request.text()
            data = json.loads(body) if body else {}

        tool_name = data.get("tool")
        if tool_name and self._on_tool_request:
            log.info("Tool requested from Cavalry panel: %s (data=%s)", tool_name, data)
            self._on_tool_request(tool_name, data)

        return web.json_response({"status": "ok"})

    def set_tool_callback(self, callback):
        """Register a callback for when Cavalry requests a tool.

        Args:
            callback (callable): Function that accepts (tool_name, data).
                Will be called from the server thread, so the callback
                should dispatch to the main thread if needed.
        """
        self._on_tool_request = callback

    async def _handle_health(self, request):
        return web.json_response({
            "connected": self.is_connected,
            "cavalry_port": self._cavalry_port,
            "scene_path": self._current_scene_path,
        })

    # ------------------------------------------------------------------
    # Convenience methods -- typed wrappers around send_command
    # ------------------------------------------------------------------

    # -- Metadata --

    def imprint(self, layer_id, data, key=None):
        """Store AYON metadata on a Cavalry layer/comp.

        Args:
            layer_id (str): Cavalry layer or comp ID.
            data (dict): Metadata payload to store.
            key (str, optional): Storage key. Use "ayon_context" for publish
                context (avoids overwriting creator instances). Default is
                instance/container data.
        """
        args = {"layer_id": str(layer_id), "data": data}
        if key:
            args["key"] = key
        self.send_command("imprint", args)

    def read(self, layer_id):
        """Read AYON metadata from a layer/comp.

        Returns:
            dict or None: Stored metadata, or None if absent.
        """
        result = self.send_command("read", {
            "layer_id": str(layer_id),
        })
        return result.get("data")

    def get_metadata(self):
        """Scan all scene layers and comps for AYON metadata.

        Returns:
            list[dict]: Each dict includes ``__layer_id__`` plus stored data.
        """
        result = self.send_command("get_metadata", timeout=15)
        return result.get("items", [])

    def get_create_context(self):
        """Get selection, comps, scene path, and metadata in one call.

        Returns:
            dict: selection, comps, scene_path, items (metadata).
        """
        result = self.send_command("get_create_context", timeout=15)
        return {
            "selection": result.get("selection", []),
            "comps": result.get("comps", []),
            "scene_path": result.get("scene_path", ""),
            "items": result.get("items", []),
        }

    def remove_metadata(self, layer_id):
        """Remove AYON metadata from a layer/comp."""
        self.send_command("remove_metadata", {
            "layer_id": str(layer_id),
        })

    # -- Compositions --

    def get_comps(self):
        """Return all compositions in the scene.

        Returns:
            list[dict]: Each dict has ``id`` and ``name``.
        """
        result = self.send_command("get_comps")
        return result.get("comps", [])

    def get_active_comp(self):
        """Return the currently active composition.

        Returns:
            dict: ``id`` and ``name`` of active comp.
        """
        return self.send_command("get_active_comp")

    def set_active_comp(self, comp_id):
        """Set the currently active composition."""
        self.send_command("set_active_comp", {"comp_id": str(comp_id)})

    def get_comp_settings(self, comp_id=None):
        """Get composition settings (resolution, fps, frame range).

        Returns:
            dict: Keys include resolution_width, resolution_height,
                frame_start, frame_end, fps, name.
        """
        args = {}
        if comp_id:
            args["comp_id"] = str(comp_id)
        return self.send_command("get_comp_settings", args)

    def set_comp_settings(self, comp_id=None, **kwargs):
        """Set composition settings.

        Keyword Args:
            resolution_width (int): Width in pixels.
            resolution_height (int): Height in pixels.
            frame_start (int): First frame.
            frame_end (int): Last frame.
            fps (float): Frame rate.
        """
        args = dict(kwargs)
        if comp_id:
            args["comp_id"] = str(comp_id)
        self.send_command("set_comp_settings", args)

    def rename_layer(self, layer_id, name):
        """Rename a layer or composition."""
        self.send_command("rename_layer", {
            "layer_id": str(layer_id),
            "name": name,
        })

    def get_layer_info(self, layer_id):
        """Get info about a layer (name, type, exists).

        Returns:
            dict: id, name, type, exists.
        """
        return self.send_command("get_layer_info", {
            "layer_id": str(layer_id),
        })

    def get_comp_layers(self, comp_id=None, top_level=False):
        """Return layers in a composition.

        Returns:
            list[dict]: Each dict has id, name, type.
        """
        args = {"top_level": top_level}
        if comp_id:
            args["comp_id"] = str(comp_id)
        result = self.send_command("get_comp_layers", args)
        return result.get("layers", [])

    # -- Assets --

    def load_asset(self, path, is_sequence=False):
        """Load an asset (image, video, audio) into the scene.

        Returns:
            str: Asset ID of the newly loaded asset.
        """
        result = self.send_command("load_asset", {
            "path": path,
            "is_sequence": is_sequence,
        })
        return result.get("asset_id", "")

    def import_scene(self, path):
        """Import a .cv or .cvc file into the scene."""
        self.send_command("import_scene", {"path": path})

    def replace_asset(self, asset_id, path):
        """Replace an existing asset's file."""
        self.send_command("replace_asset", {
            "asset_id": str(asset_id),
            "path": path,
        })

    def add_asset_to_comp(self, asset_id):
        """Add an asset to the active composition as a Footage Shape.

        Returns:
            tuple: (footage_id, offset) - offset is the delta to move clip to
                current playhead. Call offset_layer_time() after load completes.
        """
        result = self.send_command("add_asset_to_comp", {
            "asset_id": str(asset_id),
        })
        footage_id = result.get("footage_id", "")
        offset = result.get("offset", 0)
        return (footage_id, offset)

    def offset_layer_time(self, layer_id, offset):
        """Offset a layer's clip in time. Call after load completes."""
        self.send_command("offset_layer_time", {
            "layer_id": str(layer_id),
            "offset": int(offset),
        })

    def get_asset_info(self, asset_id):
        """Get info about an asset.

        Returns:
            dict: asset_id, file_path, asset_type, is_file_asset.
        """
        return self.send_command("get_asset_info", {
            "asset_id": str(asset_id),
        })

    def get_asset_window_layers(self, top_level=False):
        """Return all layers in the Asset Window.

        Returns:
            list[dict]: Each dict has id, name, type.
        """
        result = self.send_command("get_asset_window_layers", {
            "top_level": top_level,
        })
        return result.get("assets", [])

    def delete_layer(self, layer_id):
        """Delete a layer from the scene."""
        self.send_command("delete_layer", {
            "layer_id": str(layer_id),
        })

    # -- Selection --

    def get_selection(self):
        """Get currently selected layers.

        Returns:
            list[dict]: Each dict has id, name, type.
        """
        result = self.send_command("get_selection")
        return result.get("selection", [])

    def select(self, layer_ids):
        """Select the specified layers in the scene."""
        self.send_command("select", {"layer_ids": list(layer_ids)})

    def export_selected(self, path):
        """Export selected (and connected) layers to a .cvc file.

        Returns:
            bool: True if export succeeded.
        """
        path = path.replace("\\", "/")
        if not path.lower().endswith(".cvc"):
            path = path + ".cvc"
        result = self.send_command("export_selected", {"path": path})
        return result.get("success", False)

    # -- Rendering --

    def get_render_queue_items(self):
        """Return all Render Queue items.

        Returns:
            list[dict]: Each dict has id, name.
        """
        result = self.send_command("get_render_queue_items")
        return result.get("items", [])

    def add_render_queue_item(self, comp_id):
        """Add a composition to the Render Queue.

        Returns:
            str: Render Queue Item ID.
        """
        result = self.send_command("add_render_queue_item", {
            "comp_id": str(comp_id),
        })
        return result.get("item_id", "")

    def create_rq_item_and_imprint(self, comp_id, data, path=None, key=None):
        """Add RQ item, set render path, and imprint in one round-trip.

        Args:
            comp_id (str): Composition ID.
            data (dict): Instance/container data to imprint.
            path (str, optional): Render output directory (forward slashes).
            key (str, optional): "ayon_context" for context data.

        Returns:
            str: Render Queue Item ID.
        """
        args = {"comp_id": str(comp_id), "data": data}
        if path:
            args["path"] = path.replace("\\", "/")
        if key:
            args["key"] = key
        result = self.send_command("create_rq_item_and_imprint", args)
        return result.get("item_id", "")

    def render(self, item_id, timeout=300):
        """Render a specific Render Queue item (blocking).

        Args:
            item_id (str): Render Queue Item ID.
            timeout (float): Max seconds to wait for render to finish.

        Returns:
            dict: Full result including render_path, scene_path,
                and item_attrs with any output-related attributes.
        """
        return self.send_command(
            "render", {"item_id": str(item_id)}, timeout=timeout
        )

    def render_all(self, timeout=600):
        """Render all Render Queue items (blocking).

        Returns:
            dict: Full result including render_path, scene_path.
        """
        return self.send_command("render_all", timeout=timeout)

    def get_render_path(self):
        """Get the current render output directory.

        Returns:
            str: Render path.
        """
        result = self.send_command("get_render_path")
        return result.get("path", "")

    def set_render_path(self, path, item_id=None):
        """Set the render output path on RQ item(s).

        Args:
            path (str): Desired output directory (use forward slashes).
            item_id (str, optional): Specific RQ item to set; if None, all items.
        """
        path = path.replace("\\", "/")
        args = {"path": path}
        if item_id:
            args["item_id"] = str(item_id)
        self.send_command("set_render_path", args)

    def get_render_queue_item_info(self, item_id):
        """Get detailed info about a Render Queue item's attributes.

        Returns:
            dict: Item info including all readable attributes.
        """
        result = self.send_command("get_render_queue_item_info", {
            "item_id": str(item_id),
        })
        return result.get("info", {})

    def get_rq_item_format(self, item_id):
        """Get output format from Render Queue item (for farm render).

        Returns:
            dict: format info with keys: format, filePath, tried, allAttrNames
        """
        return self.send_command("get_rq_item_format", {
            "item_id": str(item_id),
        })

    # -- Scene helpers --

    def save(self):
        """Save the current scene."""
        return self.send_command("save_scene")

    def get_active_document_full_name(self):
        """Get the full path of the current scene file.

        Returns:
            str: Scene file path or empty string.
        """
        result = self.send_command("get_scene_path", timeout=5)
        return result.get("path", "")


class _ServerThread(threading.Thread):
    """Runs the aiohttp server in a dedicated thread with its own loop."""

    def __init__(self, app, port):
        super().__init__(daemon=True)
        self._app = app
        self._port = port
        self._loop = None
        self._runner = None
        self.is_running = False

    def run(self):
        self.is_running = True
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._start())
            self._loop.run_forever()
        except Exception:
            log.error("HTTP server thread crashed", exc_info=True)
        finally:
            self.is_running = False
            if self._loop and not self._loop.is_closed():
                self._loop.close()
            log.info("HTTP server thread exited")

    async def _start(self):
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "localhost", self._port)
        await site.start()
        log.info("HTTP server listening on localhost:%d", self._port)

    def stop(self):
        self.is_running = False
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._shutdown(), self._loop
            )

    async def _shutdown(self):
        if self._runner:
            await self._runner.cleanup()
        self._loop.stop()
