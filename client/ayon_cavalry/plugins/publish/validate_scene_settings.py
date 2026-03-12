"""Validate composition settings against AYON folder/task attributes.

Checks fps, resolution, and frame range match what is configured
in the AYON project for the target folder/task.
"""

import re

import pyblish.api

from ayon_core.pipeline import (
    PublishValidationError,
    OptionalPyblishPluginMixin,
)
from ayon_core.pipeline.publish import RepairAction

from ayon_cavalry.api import get_stub


class ValidateSceneSettings(
    OptionalPyblishPluginMixin,
    pyblish.api.InstancePlugin,
):
    """Ensure Composition settings match AYON folder/task attributes.

    Compares fps, resolution, and frame range of the Cavalry composition
    against the expected values from the project database.

    If this fails, check the error message for the discrepancy and adjust
    the Composition settings accordingly. Alternatively, uncheck this
    validation before the Validation phase if you know what you are doing.
    """

    order = pyblish.api.ValidatorOrder
    label = "Validate Scene Settings"
    actions = [RepairAction]
    families = ["render.local", "render"]
    hosts = ["cavalry"]
    settings_category = "cavalry"
    optional = True

    skip_timelines_check = [".*"]
    skip_resolution_check = [".*"]

    def process(self, instance):
        if not self.is_active(instance.data):
            return

        entity = (
            instance.data.get("taskEntity")
            or instance.data.get("folderEntity")
        )
        if not entity:
            self.log.debug("No entity found, skipping validation")
            return

        attribs = entity.get("attrib", {})
        if not attribs:
            self.log.debug("No attributes on entity, skipping")
            return

        expected = {}
        if attribs.get("fps"):
            expected["fps"] = float(attribs["fps"])
        if attribs.get("resolutionWidth"):
            expected["resolutionWidth"] = attribs["resolutionWidth"]
        if attribs.get("resolutionHeight"):
            expected["resolutionHeight"] = attribs["resolutionHeight"]
        if attribs.get("frameStart") is not None:
            expected["frameStart"] = attribs["frameStart"]
        if attribs.get("frameEnd") is not None:
            expected["frameEnd"] = attribs["frameEnd"]

        task_name = instance.data.get("task", "")

        if any(
            re.search(pattern, task_name)
            for pattern in self.skip_resolution_check
        ):
            expected.pop("resolutionWidth", None)
            expected.pop("resolutionHeight", None)

        if any(
            re.search(pattern, task_name)
            for pattern in self.skip_timelines_check
        ):
            expected.pop("fps", None)
            expected.pop("frameStart", None)
            expected.pop("frameEnd", None)

        if not expected:
            self.log.debug("No settings to validate after filtering")
            return

        current = {
            "fps": instance.data.get("fps"),
            "frameStart": instance.data.get("frameStart"),
            "frameEnd": instance.data.get("frameEnd"),
            "resolutionWidth": instance.data.get("resolutionWidth"),
            "resolutionHeight": instance.data.get("resolutionHeight"),
        }

        invalid_settings = []
        for key, value in expected.items():
            current_val = current.get(key)
            if key == "fps" and current_val is not None:
                current_val = float("{:.2f}".format(float(current_val)))
                value = float("{:.2f}".format(float(value)))
            if value != current_val:
                invalid_settings.append(
                    "'{}' expected: '{}'  found: '{}'".format(
                        key, value, current_val
                    )
                )

        if invalid_settings:
            msg = "Found invalid settings:\n{}".format(
                "\n".join(invalid_settings)
            )
            raise PublishValidationError(self, msg)

    @classmethod
    def repair(cls, instance):
        """Apply expected settings to the composition."""
        entity = (
            instance.data.get("taskEntity")
            or instance.data.get("folderEntity")
        )
        if not entity:
            return

        attribs = entity.get("attrib", {})
        comp_id = instance.data.get("comp_id")
        if not comp_id:
            return

        stub = get_stub()
        settings = {}
        if attribs.get("fps"):
            settings["fps"] = attribs["fps"]
        if attribs.get("resolutionWidth"):
            settings["resolution_width"] = attribs["resolutionWidth"]
        if attribs.get("resolutionHeight"):
            settings["resolution_height"] = attribs["resolutionHeight"]
        if attribs.get("frameStart") is not None:
            settings["frame_start"] = attribs["frameStart"]
        if attribs.get("frameEnd") is not None:
            settings["frame_end"] = attribs["frameEnd"]

        if settings:
            stub.set_comp_settings(comp_id=comp_id, **settings)
