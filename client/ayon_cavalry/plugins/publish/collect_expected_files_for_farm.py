"""Collect expected files for Cavalry farm render.

Builds expectedFiles from workfile path and instance data so the Deadline
submit plugin and submit_publish_job know where to find rendered output.
Format is read from the Render Queue item's generator connection in Cavalry
(renderMP4, renderPNG, etc.).
"""

import os

import pyblish.api

from ayon_cavalry.api import get_stub


# Map Cavalry format values (from RQ item) to file extension
# Cavalry may return "png", "PNG", "jpeg", "Jpeg", etc.
CAVALRY_FORMAT_TO_EXT = {
    "png": "png",
    "jpeg": "jpeg",
    "jpg": "jpeg",
    "svg": "svg",
    "gif": "gif",
    "apng": "apng",
    "webm": "webm",
    "webp": "webp",
    "mp4": "mp4",
    "mov": "mov",
    "quicktime": "mov",
    "qt": "mov",
    "audio": "audio",
}


def _parse_format_value(value, log):
    """Parse format value from Cavalry (string, enum int, or dict) to file extension."""
    if value is None:
        return None
    if isinstance(value, dict):
        options = value.get("options")
        idx = value.get("value") or value.get("index") or value.get(
            "dropdownIndex"
        )
        if options is not None and isinstance(idx, (int, float)):
            idx = int(idx)
            if 0 <= idx < len(options):
                return _parse_format_value(options[idx], log)
        if idx is not None:
            return _parse_format_value(idx, log)
    if isinstance(value, str):
        ext = CAVALRY_FORMAT_TO_EXT.get(value.lower(), value.lower())
        if ext in ("png", "jpeg", "svg", "gif", "apng", "webm",
                   "webp", "mp4", "mov", "audio"):
            return ext
    elif isinstance(value, (int, float)):
        cli_formats = [
            "png", "jpeg", "svg", "gif", "apng", "webm",
            "webp", "mp4", "quicktime", "audio"
        ]
        idx = int(value)
        if 0 <= idx < len(cli_formats):
            fmt = cli_formats[idx]
            return "mov" if fmt == "quicktime" else fmt
    return None


def _get_format_from_rq_item(stub, rq_item_id, log):
    """Get output format from Render Queue item attributes.

    Uses get_rq_item_format to try known attribute names, then falls back
    to scanning all attributes for format-like keys, then filePath extension.
    """
    try:
        result = stub.get_rq_item_format(rq_item_id)
        fmt_info = result.get("format")
        if fmt_info:
            raw_value = fmt_info.get("value")
            ext = _parse_format_value(raw_value, log)
            if ext:
                return ext

        file_path = result.get("filePath")
        if isinstance(file_path, dict) and "value" in file_path:
            file_path = file_path["value"]
        if file_path and isinstance(file_path, str):
            _, ext = os.path.splitext(file_path)
            ext = ext.lstrip(".").lower()
            if ext and ext in CAVALRY_FORMAT_TO_EXT:
                return CAVALRY_FORMAT_TO_EXT.get(ext, ext)

        info = stub.get_render_queue_item_info(rq_item_id)
        attrs = info.get("attributes", {})
        for key, value in attrs.items():
            if "format" not in key.lower():
                continue
            ext = _parse_format_value(value, log)
            if ext:
                return ext

        # Value-based scan: try attributes with format-like names we haven't
        # checked (Cavalry may use outputType, fileType, exportFormat, etc.)
        format_like = ("format", "output", "filetype", "export", "render")
        exclude = ("path", "directory", "filepath", "range", "start", "end")
        for key, value in attrs.items():
            key_lower = key.lower()
            if any(ex in key_lower for ex in exclude):
                continue
            if any(fl in key_lower for fl in format_like):
                ext = _parse_format_value(value, log)
                if ext:
                    return ext

        all_names = result.get("allAttrNames", [])
        if all_names:
            format_like_attrs = {
                k: v for k, v in attrs.items()
                if any(fl in k.lower() for fl in format_like)
                and not any(ex in k.lower() for ex in exclude)
            }
            log.warning(
                "RQ item format not found. Tried: %s. Format-like attrs: %s. "
                "Use 'Copy Scripting Path' on the format dropdown in Cavalry.",
                result.get("tried", []),
                format_like_attrs,
            )
            log.debug("All RQ item attributes: %s", attrs)
    except Exception as e:
        log.debug("Could not get format from RQ item: %s", e)
    return None


class CollectExpectedFilesForFarm(pyblish.api.InstancePlugin):
    """Build expectedFiles for render.farm instances.

    Output path mirrors AE: workfile_dir/renders/cavalry/{workfile_stem}/
    Filename: {product}_v{version:03d}.{frame}.{ext}
    Format is read from the Render Queue item configured in Cavalry.
    """

    order = pyblish.api.CollectorOrder + 0.15
    label = "Collect Expected Files for Farm"
    hosts = ["cavalry"]
    families = ["render.farm"]

    # Cavalry CLI uses 5-digit frame padding by default
    padding = 5
    default_format = "png"

    def process(self, instance):
        if not instance.data.get("farm"):
            return

        current_file = instance.context.data.get("currentFile", "")
        if not current_file:
            self.log.warning("No current file, cannot build expected files")
            return

        workfile_dir = os.path.dirname(current_file)
        workfile_stem = os.path.splitext(os.path.basename(current_file))[0]
        output_dir = os.path.join(
            workfile_dir, "renders", "cavalry", workfile_stem
        )
        output_dir = os.path.normpath(output_dir).replace("\\", "/")

        product_name = instance.data.get("productName", "render")
        version = instance.context.data.get("version", 1)
        version_str = "v{:03d}".format(version)
        frame_start = int(instance.data["frameStart"])
        frame_end = int(instance.data["frameEnd"])

        # Get format: manual override first, then Render Queue item
        ext = self.default_format
        creator_attrs = instance.data.get("creator_attributes", {})
        manual_format = creator_attrs.get("format", "").strip().lower()
        if manual_format and manual_format in CAVALRY_FORMAT_TO_EXT:
            ext = CAVALRY_FORMAT_TO_EXT.get(manual_format, manual_format)
            if ext in ("png", "jpeg", "svg", "gif", "apng", "webm",
                       "webp", "mp4", "mov", "audio"):
                self.log.debug("Using manual format override: %s", ext)
        elif manual_format:
            parsed = _parse_format_value(manual_format, self.log)
            if parsed:
                ext = parsed
                self.log.debug("Using manual format override: %s", ext)
        rq_item_id = instance.data.get("__layer_id__")
        if ext == self.default_format and rq_item_id:
            try:
                stub = get_stub()
                rq_format = _get_format_from_rq_item(stub, rq_item_id, self.log)
                if rq_format:
                    ext = rq_format
            except Exception as e:
                self.log.warning(
                    "Could not read format from Render Queue, using default: %s",
                    e,
                )

        expected_files = []
        video_formats = {"mp4", "webm", "mov"}
        if ext in video_formats:
            filename = "{}_{}.{}".format(product_name, version_str, ext)
            filepath = os.path.join(output_dir, filename).replace("\\", "/")
            expected_files.append(filepath)
        else:
            for frame in range(frame_start, frame_end + 1):
                frame_str = str(frame).zfill(self.padding)
                filename = "{}_{}.{}.{}".format(
                    product_name, version_str, frame_str, ext
                )
                filepath = os.path.join(output_dir, filename).replace("\\", "/")
                expected_files.append(filepath)

        instance.data["expectedFiles"] = expected_files
        instance.data["outputDir"] = output_dir

        self.log.info(
            "Expected %d files in %s (format: %s)",
            len(expected_files),
            output_dir,
            ext,
        )
