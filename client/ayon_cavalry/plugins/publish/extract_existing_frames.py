"""Publish render files that are already on disk.

Used when the instance render target is "Use existing frames". Cavalry is
not asked to render again. Multi-comp publishes read the last render
manifest when it is still beside the output, then fall back to matching
files in the Render Queue item's current output folder.
"""

import os

from ayon_core.pipeline import publish

from ayon_cavalry.api import get_stub
from ayon_cavalry.api.publish_thumbnail import tag_need_thumbnail
from ayon_cavalry.plugins.publish.extract_local_render import (
    IMAGE_EXTS,
    ExtractLocalRender,
)
from ayon_cavalry.plugins.publish.extract_multi_comp_local_render import (
    ExtractMultiCompLocalRender,
)


class ExtractExistingFrames(publish.Extractor):
    """Collect the latest rendered files without starting a new render."""

    order = publish.Extractor.order - 0.45
    label = "Extract Existing Frames"
    hosts = ["cavalry"]
    families = ["render.frames"]

    def process(self, instance):
        if instance.data.get("creator_attributes", {}).get("multi_comp"):
            helper = ExtractMultiCompLocalRender()
            helper.log = self.log
            helper.collect_existing_outputs(instance)
            return
        self._collect_single(instance)

    def _collect_single(self, instance):
        rq_item_id = instance.data.get("__layer_id__")
        if not rq_item_id:
            message = "Existing-frames publish has no Render Queue item."
            self.log.error(message)
            raise publish.PublishError(message)

        output_path = ExtractLocalRender()._get_rq_item_output_dir(
            get_stub(), rq_item_id
        )
        output_dir = _as_output_directory(output_path)
        if not output_dir:
            message = (
                "No existing render output directory for RQ item {}."
                .format(rq_item_id)
            )
            self.log.error(message)
            raise publish.PublishError(message)

        output_dir, files = latest_existing_media(output_dir)
        if not files:
            message = (
                "No existing render files in {}.".format(output_dir)
            )
            self.log.error(message)
            raise publish.PublishError(message)

        self.log.info(
            "Collecting %d existing frame file(s) from %s",
            len(files),
            output_dir,
        )
        representations = ExtractLocalRender()._build_representations(
            output_dir, files, instance
        )
        thumb_repre = tag_need_thumbnail(representations)
        if thumb_repre:
            self.log.info(
                "Tagged representation %r with need_thumbnail for version thumbnail",
                thumb_repre,
            )
        instance.data["representations"] = representations
        instance.data["stagingDir"] = output_dir


def _as_output_directory(path):
    """Return a directory for an RQ filePath that may point at a file."""
    if not path:
        return None
    normalized = os.path.normpath(path)
    if os.path.isdir(normalized):
        return normalized
    parent = os.path.dirname(normalized)
    if parent and os.path.isdir(parent):
        return parent
    return None


def _media_names(directory):
    names = []
    try:
        entries = os.listdir(directory)
    except OSError:
        return names
    for name in entries:
        file_path = os.path.join(directory, name)
        if not os.path.isfile(file_path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in IMAGE_EXTS:
            names.append(name)
    return sorted(names)


def _newest_mtime(directory, names):
    latest = None
    for name in names:
        try:
            mtime = os.path.getmtime(os.path.join(directory, name))
        except OSError:
            continue
        if latest is None or mtime > latest:
            latest = mtime
    return latest


def latest_existing_media(output_dir):
    """Return ``(directory, filenames)`` for the latest media in ``output_dir``.

    Files directly in the Render Queue folder win. Otherwise the child folder
    whose media was written most recently is used. Sibling version folders
    outside ``output_dir`` are not searched.
    """
    direct = _media_names(output_dir)
    if direct:
        return output_dir, direct

    best_dir = None
    best_names = []
    best_mtime = None
    try:
        children = os.listdir(output_dir)
    except OSError:
        children = []
    for name in children:
        subdir = os.path.join(output_dir, name)
        if not os.path.isdir(subdir):
            continue
        names = _media_names(subdir)
        if not names:
            continue
        mtime = _newest_mtime(subdir, names)
        if mtime is None:
            continue
        if best_mtime is None or mtime > best_mtime:
            best_dir = subdir
            best_names = names
            best_mtime = mtime
    if best_dir:
        return best_dir, best_names
    return output_dir, []
