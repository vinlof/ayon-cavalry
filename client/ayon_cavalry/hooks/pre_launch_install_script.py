"""Pre-launch hook to install the AYON panel script into Cavalry.

Copies ayon_panel.js to the Cavalry Scripts folder so it appears in
Cavalry's Window > Scripts > AYON menu.
"""

import os
import shutil
from pathlib import Path

import platformdirs

from ayon_cavalry import CAVALRY_ADDON_ROOT
from ayon_applications import PreLaunchHook, LaunchTypes


class InstallAyonScriptToCavalry(PreLaunchHook):
    """Copy the AYON panel script to Cavalry's Scripts folder.

    Compares file contents and only overwrites when changed, so the
    script stays up to date across addon versions.
    """

    app_groups = {"cavalry"}
    order = 1
    launch_types = {LaunchTypes.local}

    def execute(self):
        try:
            settings = self.data["project_settings"]["cavalry"]
            if not settings.get("auto_install_script", True):
                self.log.debug(
                    "Auto-install of AYON panel script is disabled."
                )
                return
        except (KeyError, TypeError):
            pass

        try:
            self._install_panel_script()
        except Exception:
            self.log.warning(
                "Failed to install AYON panel script to Cavalry.",
                exc_info=True,
            )

    def _install_panel_script(self):
        source_dir = Path(
            CAVALRY_ADDON_ROOT, "api", "js"
        )
        source_file = source_dir / "ayon_panel.js"

        if not source_file.exists():
            self.log.error(
                "AYON panel script not found at: %s", source_file
            )
            return

        # Cavalry Scripts folder: %APPDATA%/Cavalry/Scripts/AYON/
        target_dir = Path(
            platformdirs.user_data_dir(roaming=True),
            "Cavalry", "Scripts", "AYON"
        )
        target_file = target_dir / "ayon_panel.js"

        # Decide if script needs copying (assets are always synced below)
        script_needs_copy = True
        if target_file.exists():
            source_content = source_file.read_text(encoding="utf-8")
            target_content = target_file.read_text(encoding="utf-8")
            if source_content == target_content:
                self.log.debug(
                    "AYON panel script is already up to date."
                )
                script_needs_copy = False
            else:
                self.log.info("Updating AYON panel script in Cavalry.")
        else:
            self.log.info("Installing AYON panel script to Cavalry.")

        target_dir.mkdir(parents=True, exist_ok=True)

        # Copy ayon_panel_assets (status icons) every launch
        self.log.debug(
            "AYON panel script source dir: %s", source_dir
        )
        for folder_name in ("ayon_panel_assets",):
            source_assets = source_dir / folder_name
            if not source_assets.is_dir():
                self.log.debug(
                    "AYON panel assets folder not found: %s",
                    source_assets,
                )
                continue
            source_files = [p.name for p in source_assets.iterdir() if p.is_file()]
            self.log.debug(
                "AYON panel assets source files: %s", source_files
            )
            target_assets = target_dir / folder_name
            target_assets.mkdir(parents=True, exist_ok=True)
            copied = 0
            for item in source_assets.iterdir():
                if item.is_file():
                    dest = target_assets / item.name
                    shutil.copy2(str(item), str(dest))
                    copied += 1
            if copied > 0:
                self.log.info(
                    "Copied %d file(s) to %s from %s",
                    copied,
                    target_assets,
                    source_assets,
                )
            else:
                self.log.warning(
                    "AYON panel asset folder is empty: %s (add ayon_green.png and ayon_red.png for status icons)",
                    source_assets,
                )

        if script_needs_copy:
            shutil.copy2(str(source_file), str(target_file))
            self.log.info(
                "AYON panel script installed to: %s", target_file
            )
