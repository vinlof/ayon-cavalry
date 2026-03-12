from ayon_server.settings import BaseSettingsModel, SettingsField


class CustomScriptEntry(BaseSettingsModel):
    """Single custom script location to install into Cavalry Scripts."""

    source_path: str = SettingsField(
        "",
        title="Source Path",
        description=(
            "Path to script file or folder. Supports env vars: ${VAR} or $VAR. "
            "Examples: C:\\Studio\\Scripts, ${STUDIO_SCRIPTS}/cavalry"
        ),
    )
    target_subfolder: str = SettingsField(
        "",
        title="Menu Subfolder Name",
        description=(
            "Name under Window > Scripts (e.g. 'StudioTools'). "
            "If empty, uses the source folder/file name."
        ),
    )


class CavalryCreatorSettings(BaseSettingsModel):
    """Settings for Cavalry creators."""

    rename_comp_to_product_name: bool = SettingsField(
        True,
        title="Rename Composition to Product Name",
        description=(
            "When creating a render instance, rename the source composition "
            "to match the product name."
        ),
    )
    force_setting_values: bool = SettingsField(
        False,
        title="Force Settings from AYON",
        description=(
            "Force fps, frame range and resolution of the composition to "
            "match the target publish context attributes when creating a render."
        ),
    )


class CavalryPublishSettings(BaseSettingsModel):
    """Settings for Cavalry publish plugins."""

    validate_scene_settings: bool = SettingsField(
        True,
        title="Validate Scene Settings",
        description=(
            "Enable validation that checks composition settings against "
            "AYON folder/task attributes before publishing."
        ),
    )
    increment_workfile: bool = SettingsField(
        True,
        title="Increment Workfile on Publish",
        description=(
            "Automatically increment the workfile version after a "
            "successful publish."
        ),
    )


class CavalrySettings(BaseSettingsModel):
    """Cavalry Project Settings."""

    auto_install_script: bool = SettingsField(
        True,
        title="Install AYON Panel Script",
        description=(
            "Automatically copy the AYON panel script to the Cavalry"
            " Scripts folder on launch."
        ),
    )
    custom_script_locations: list[CustomScriptEntry] = SettingsField(
        default_factory=list,
        title="Custom Script Locations",
        description=(
            "Additional script locations to install into Cavalry on launch. "
            "Each entry is copied fresh (target cleared first) to ensure "
            "Cavalry Scripts match the source."
        ),
    )
    creator: CavalryCreatorSettings = SettingsField(
        default_factory=CavalryCreatorSettings,
        title="Creator Settings",
    )
    publish: CavalryPublishSettings = SettingsField(
        default_factory=CavalryPublishSettings,
        title="Publish Settings",
    )


DEFAULT_CAVALRY_SETTING = {
    "auto_install_script": True,
    "custom_script_locations": [],
    "creator": {
        "rename_comp_to_product_name": True,
        "force_setting_values": False,
    },
    "publish": {
        "validate_scene_settings": True,
        "increment_workfile": True,
    },
}
