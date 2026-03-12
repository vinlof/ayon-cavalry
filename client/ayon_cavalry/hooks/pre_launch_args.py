"""Pre-launch hook to set up Cavalry launch arguments.

Wraps the launch so that Python's launch_script.py runs first (starting
the HTTP server) and then Cavalry is launched as a subprocess.
"""

import os
import platform
import subprocess

from ayon_core.lib import (
    get_ayon_launcher_args,
    is_using_ayon_console,
)
from ayon_applications import PreLaunchHook, LaunchTypes
from ayon_cavalry import get_launch_script_path


def get_launch_kwargs(kwargs):
    """Set platform-specific Popen kwargs for Cavalry launch."""
    if kwargs is None:
        kwargs = {}

    if platform.system().lower() != "windows":
        return kwargs

    if is_using_ayon_console():
        kwargs.update({
            "creationflags": subprocess.CREATE_NEW_CONSOLE,
        })
    else:
        kwargs.update({
            "creationflags": subprocess.CREATE_NO_WINDOW,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        })
    return kwargs


class CavalryPrelaunchHook(PreLaunchHook):
    """Prepare launch arguments for Cavalry.

    Inserts Python executable and the AYON launch script before the
    Cavalry executable path, so the Python process starts first and
    manages the Cavalry subprocess.
    """

    app_groups = {"cavalry"}
    order = 20
    launch_types = {LaunchTypes.local}

    def execute(self):
        # Pop the Cavalry executable path
        executable_path = self.launch_context.launch_args.pop(0)

        # Pop any remaining args (there shouldn't normally be others)
        remainders = []
        while self.launch_context.launch_args:
            remainders.append(self.launch_context.launch_args.pop(0))

        script_path = get_launch_script_path()

        new_launch_args = get_ayon_launcher_args(
            "run", script_path, executable_path
        )

        # Add workfile path if exists
        workfile_path = self.data.get("last_workfile_path")
        if (
            self.data.get("start_last_workfile")
            and workfile_path
            and os.path.exists(workfile_path)
        ):
            new_launch_args.append(workfile_path)

        # Workfiles tool on launch
        workfile_startup = self.data.get("workfile_startup", False)
        self.launch_context.env[
            "AYON_CAVALRY_WORKFILES_ON_LAUNCH"
        ] = str(workfile_startup).lower()

        self.launch_context.launch_args.append(new_launch_args)

        if remainders:
            self.launch_context.launch_args.extend(remainders)

        self.launch_context.kwargs = get_launch_kwargs(
            self.launch_context.kwargs
        )
