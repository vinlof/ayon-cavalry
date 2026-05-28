"""Pre-launch hook to install the AYON panel script into Cavalry.

Copies ayon_panel.js to the Cavalry Scripts folder so it appears in
Cavalry's Window > Scripts > AYON menu. Also installs custom script
locations from project settings.
"""

import os
import re
import shutil
from pathlib import Path

import platformdirs

from ayon_cavalry import CAVALRY_ADDON_ROOT
from ayon_applications import PreLaunchHook, LaunchTypes


def _sanitize_subfolder_name(name: str) -> str:
    """Remove path separators and invalid chars from subfolder name."""
    sanitized = re.sub(r'[/\\:*?"<>|]', "_", name)
    return sanitized.strip() or "Custom"


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
        except (KeyError, TypeError):
            settings = {}

        if settings.get("auto_install_script", True):
            try:
                self._install_panel_script()
            except Exception:
                self.log.warning(
                    "Failed to install AYON panel script to Cavalry.",
                    exc_info=True,
                )
        else:
            self.log.debug(
                "Auto-install of AYON panel script is disabled."
            )

        try:
            self._install_custom_scripts(settings)
        except Exception:
            self.log.warning(
                "Failed to install custom scripts to Cavalry.",
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

        self._install_script_helper(source_dir, target_dir)

    def _install_script_helper(self, source_dir: Path, target_dir: Path) -> None:
        """Copy generic AYON script helpers beside the panel script."""
        source_file = source_dir / "ayon_script_helpers.js"
        if not source_file.exists():
            self.log.warning(
                "AYON script helpers not found at: %s", source_file
            )
            return

        target_file = target_dir / "ayon_script_helpers.js"
        source_content = source_file.read_text(encoding="utf-8")
        if target_file.exists():
            target_content = target_file.read_text(encoding="utf-8")
            if source_content == target_content:
                self.log.debug("AYON script helpers are already up to date.")
                return
            self.log.info("Updating AYON script helpers in Cavalry.")
        else:
            self.log.info("Installing AYON script helpers to Cavalry.")

        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source_file), str(target_file))
        self.log.info("AYON script helpers installed to: %s", target_file)

    def _install_custom_scripts(self, settings: dict) -> None:
        """Install custom script locations to Cavalry Scripts (fresh install)."""
        entries = settings.get("custom_script_locations") or []
        if not entries:
            return

        scripts_root = Path(
            platformdirs.user_data_dir(roaming=True),
            "Cavalry", "Scripts"
        )

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            source_path_raw = entry.get("source_path", "").strip()
            if not source_path_raw:
                self.log.debug("Skipping custom script: empty source path.")
                continue

            source_path = Path(
                os.path.expandvars(os.path.expanduser(source_path_raw))
            )
            if not source_path.exists():
                self.log.warning(
                    "Custom script source does not exist, skipping: %s",
                    source_path,
                )
                continue

            target_subfolder_raw = entry.get("target_subfolder", "").strip()
            if target_subfolder_raw:
                target_subfolder = _sanitize_subfolder_name(
                    target_subfolder_raw
                )
            else:
                if source_path.is_file():
                    target_subfolder = _sanitize_subfolder_name(
                        source_path.stem
                    )
                else:
                    target_subfolder = _sanitize_subfolder_name(
                        source_path.name
                    )

            target_dir = scripts_root / target_subfolder

            try:
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                target_dir.mkdir(parents=True, exist_ok=True)

                if source_path.is_file():
                    dest_file = target_dir / source_path.name
                    shutil.copy2(str(source_path), str(dest_file))
                    self.log.info(
                        "Installed custom script: %s -> %s",
                        source_path.name,
                        target_dir,
                    )
                else:
                    for item in source_path.iterdir():
                        dest = target_dir / item.name
                        if item.is_file():
                            shutil.copy2(str(item), str(dest))
                        elif item.is_dir():
                            shutil.copytree(str(item), str(dest))
                    self.log.info(
                        "Installed custom script folder: %s -> %s",
                        source_path,
                        target_dir,
                    )
            except Exception:
                self.log.warning(
                    "Failed to install custom script from %s to %s",
                    source_path,
                    target_dir,
                    exc_info=True,
                )
