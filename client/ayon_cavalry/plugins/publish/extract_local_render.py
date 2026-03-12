"""Extract local render from Cavalry.

Triggers Cavalry's render queue for the composition and collects
the output files. Snapshots the output directory before rendering
so only newly created files are collected.

Render instances are stored on render queue items. The instance
__layer_id__ is the RQ item to render (no add-to-queue step).
"""

import os
import time

from ayon_core.pipeline import publish

from ayon_cavalry.api import get_stub

IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".exr", ".tiff", ".tif",
    ".tga", ".bmp", ".mp4", ".mov", ".avi", ".svg",
}


class ExtractLocalRender(publish.Extractor):
    """Render locally in Cavalry and collect output files."""

    order = publish.Extractor.order - 0.47
    label = "Extract Local Render"
    hosts = ["cavalry"]
    families = ["render.local"]

    def process(self, instance):
        if instance.data.get("creator_attributes", {}).get("multi_comp"):
            return

        stub = get_stub()
        rq_item_id = instance.data.get("__layer_id__")
        if not rq_item_id:
            comp_id = instance.data.get("comp_id") or (
                instance.data.get("members") or [None]
            )[0]
            if comp_id:
                rq_item_id = stub.add_render_queue_item(comp_id)
                self.log.info(
                    "Added comp %s to render queue as %s (legacy instance)",
                    comp_id,
                    rq_item_id,
                )
        if not rq_item_id:
            self.log.warning(
                "No __layer_id__ (RQ item) or comp_id on instance, skipping"
            )
            return

        rq_output_dir = self._get_rq_item_output_dir(stub, rq_item_id)
        if rq_output_dir:
            os.makedirs(rq_output_dir, exist_ok=True)
        candidate_dirs = self._get_candidate_dirs(stub, instance, rq_output_dir)

        pre_render_files = {}
        for d in candidate_dirs:
            if os.path.isdir(d):
                pre_render_files[d] = set(os.listdir(d))

        render_start = time.time()

        render_result = stub.render(rq_item_id, timeout=600)
        self.log.info("Render completed for %s", rq_item_id)

        if render_result:
            extra = self._dirs_from_render_result(render_result)
            for d in extra:
                if d not in pre_render_files and os.path.isdir(d):
                    pre_render_files[d] = set()
            if render_result.get("item_attrs", {}).get("__all_attrs__"):
                self.log.debug(
                    "RQ item attributes: %s",
                    render_result["item_attrs"]["__all_attrs__"],
                )

        output_dir, new_files = self._find_new_files(
            pre_render_files, render_start
        )

        if not output_dir or not new_files:
            self.log.error(
                "Could not locate newly rendered files. "
                "Candidate dirs checked: %s  Render result: %s",
                list(pre_render_files.keys()),
                render_result,
            )
            instance.data["representations"] = []
            return

        self.log.info(
            "Found %d new file(s) in: %s", len(new_files), output_dir
        )

        instance.data["stagingDir"] = output_dir
        representations = self._build_representations(
            output_dir, new_files, instance
        )
        instance.data["representations"] = representations

        self.log.info(
            "Collected %d representation(s) from %s",
            len(representations),
            output_dir,
        )

    def _get_rq_item_output_dir(self, stub, rq_item_id):
        """Get output directory from RQ item's filePath attribute."""
        try:
            info = stub.get_render_queue_item_info(rq_item_id)
            attrs = info.get("attributes", {})
            file_path = attrs.get("filePath")
            if file_path and isinstance(file_path, str):
                return os.path.normpath(file_path)
            if isinstance(file_path, dict) and "value" in file_path:
                return os.path.normpath(file_path["value"])
        except Exception:
            pass
        return None

    def _get_candidate_dirs(self, stub, instance, rq_output_dir=None):
        """Build list of directories where Cavalry might render to."""
        dirs = []

        if rq_output_dir:
            dirs.append(rq_output_dir)

        try:
            render_path = stub.get_render_path()
            if render_path:
                dirs.append(os.path.normpath(render_path))
        except Exception:
            pass

        current_file = instance.context.data.get("currentFile", "")
        if current_file:
            work_dir = os.path.normpath(os.path.dirname(current_file))
            dirs.append(work_dir)
            dirs.append(os.path.join(work_dir, "render"))
            dirs.append(os.path.join(work_dir, "Render"))
            dirs.append(os.path.join(work_dir, "renders"))

        try:
            scene_path = stub.get_active_document_full_name()
            if scene_path:
                scene_dir = os.path.normpath(os.path.dirname(scene_path))
                if scene_dir not in dirs:
                    dirs.append(scene_dir)
                    dirs.append(os.path.join(scene_dir, "render"))
                    dirs.append(os.path.join(scene_dir, "Render"))
                    dirs.append(os.path.join(scene_dir, "renders"))
        except Exception:
            pass

        home = os.path.expanduser("~")
        dirs.append(os.path.join(home, "Desktop"))
        dirs.append(os.path.join(home, "Documents"))

        seen = set()
        unique = []
        for d in dirs:
            if d and d not in seen:
                seen.add(d)
                unique.append(d)
        return unique

    def _dirs_from_render_result(self, render_result):
        """Extract additional directory candidates from the render result."""
        dirs = []
        item_attrs = render_result.get("item_attrs", {})

        file_path = item_attrs.get("filePath")
        if file_path and isinstance(file_path, str) and os.path.sep in file_path:
            dirs.append(os.path.normpath(file_path))
        elif isinstance(file_path, dict) and "value" in file_path:
            dirs.append(os.path.normpath(file_path["value"]))

        for key, value in item_attrs.items():
            if key.startswith("__"):
                continue
            if isinstance(value, str) and value:
                if os.path.sep in value or "/" in value:
                    dirs.append(os.path.normpath(value))
                    parent = os.path.dirname(value)
                    if parent:
                        dirs.append(os.path.normpath(parent))

        rp = render_result.get("render_path", "")
        if rp:
            dirs.append(os.path.normpath(rp))

        sp = render_result.get("scene_path", "")
        if sp:
            sd = os.path.normpath(os.path.dirname(sp))
            dirs.append(sd)
            dirs.append(os.path.join(sd, "Render"))
            dirs.append(os.path.join(sd, "renders"))

        return dirs

    def _find_new_files(self, pre_render_files, render_start):
        """Find files that appeared or were modified after render started.

        Returns:
            tuple: (output_dir, list_of_new_filenames) or (None, [])
        """
        for directory, old_files in pre_render_files.items():
            if not os.path.isdir(directory):
                continue

            current_files = set(os.listdir(directory))
            brand_new = current_files - old_files

            new_renders = []
            for fname in brand_new:
                _, ext = os.path.splitext(fname)
                if ext.lower() in IMAGE_EXTS:
                    new_renders.append(fname)

            if not new_renders:
                for fname in current_files:
                    _, ext = os.path.splitext(fname)
                    if ext.lower() not in IMAGE_EXTS:
                        continue
                    fpath = os.path.join(directory, fname)
                    try:
                        mtime = os.path.getmtime(fpath)
                        if mtime >= render_start - 2:
                            new_renders.append(fname)
                    except OSError:
                        pass

            if new_renders:
                return directory, sorted(new_renders)

        for directory in pre_render_files:
            if not os.path.isdir(directory):
                continue
            subdir_files = self._find_new_files_in_subdirs(
                directory, render_start
            )
            if subdir_files:
                return subdir_files[0], subdir_files[1]

        return None, []

    def _find_new_files_in_subdirs(self, directory, render_start):
        """Search subdirs for new/modified image files."""
        try:
            for name in os.listdir(directory):
                subpath = os.path.join(directory, name)
                if not os.path.isdir(subpath):
                    continue
                new_renders = []
                for fname in os.listdir(subpath):
                    _, ext = os.path.splitext(fname)
                    if ext.lower() in IMAGE_EXTS:
                        fpath = os.path.join(subpath, fname)
                        try:
                            if os.path.getmtime(fpath) >= render_start - 2:
                                new_renders.append(fname)
                        except OSError:
                            pass
                if new_renders:
                    return subpath, sorted(new_renders)
                result = self._find_new_files_in_subdirs(
                    subpath, render_start
                )
                if result:
                    return result
        except OSError:
            pass
        return None

    def _build_representations(self, output_dir, new_files, instance):
        """Group new files by extension into representations."""
        by_ext = {}
        for fname in new_files:
            _, ext = os.path.splitext(fname)
            ext = ext[1:].lower()
            by_ext.setdefault(ext, []).append(fname)

        representations = []
        for ext, files in by_ext.items():
            if len(files) == 1:
                resulting_files = files[0]
            else:
                resulting_files = sorted(files)

            repre_data = {
                "name": ext,
                "ext": ext,
                "files": resulting_files,
                "stagingDir": output_dir,
            }

            if isinstance(resulting_files, list):
                repre_data["frameStart"] = instance.data.get("frameStart")
                repre_data["frameEnd"] = instance.data.get("frameEnd")

            if (
                instance.data.get("review", False)
                and not representations
            ):
                repre_data["tags"] = ["review"]

            representations.append(repre_data)

        return representations
