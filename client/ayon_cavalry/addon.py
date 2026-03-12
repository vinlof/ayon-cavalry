import os

from ayon_core.addon import AYONAddon, IHostAddon

from .version import __version__

CAVALRY_ADDON_ROOT = os.path.dirname(os.path.abspath(__file__))


class CavalryAddon(AYONAddon, IHostAddon):
    name = "cavalry"
    version = __version__
    host_name = "cavalry"

    def add_implementation_envs(self, env, _app):
        """Modify environments to contain all required for implementation."""
        defaults = {
            "AYON_LOG_NO_COLORS": "1",
            "AYON_CAVALRY_PYTHON_PORT": "8098",
            "AYON_CAVALRY_WEBSERVER_PORT": "8099",
        }
        for key, value in defaults.items():
            if not env.get(key):
                env[key] = value

    def get_workfile_extensions(self):
        return [".cv"]

    def get_launch_hook_paths(self, app):
        if app.host_name != self.host_name:
            return []
        return [
            os.path.join(CAVALRY_ADDON_ROOT, "hooks")
        ]


def get_launch_script_path():
    return os.path.join(
        CAVALRY_ADDON_ROOT, "api", "launch_script.py"
    )
