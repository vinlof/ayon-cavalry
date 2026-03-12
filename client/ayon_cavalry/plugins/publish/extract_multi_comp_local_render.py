"""Extract local render from Cavalry for multi-comp instances.

One RQ item with multiple comp targets. Renders once; Cavalry outputs
each comp (e.g. to subdirs via Dynamic Rendering). Collects and builds
one representation per comp/output location.
"""

import os
import re
import time

from ayon_core.pipeline import publish

from ayon_cavalry.api import get_stub

IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".exr", ".tiff", ".tif",
    ".tga", ".bmp", ".mp4", ".mov", ".avi", ".svg",
}


def _sanitize_comp_name(name):
    """Sanitize comp name for representation and filesystem."""
    sanitized = re.sub(r"[^\w\-]", "_", str(name)).strip("_")
    return sanitized or "comp"


class ExtractMultiCompLocalRender(publish.Extractor):
    """Render multi-comp RQ item (one item, multiple targets) and collect outputs."""

    order = publish.Extractor.order - 0.46
    label = "Extract Multi-Comp Local Render"
    hosts = ["cavalry"]
    families = ["render.local"]

    def process(self, instance):
        if not instance.data.get("creator_attributes", {}).get("multi_comp"):
            return

        rq_item_id = instance.data.get("__layer_id__")
        if not rq_item_id:
            self.log.warning("Multi-comp instance has no __layer_id__")
            instance.data["representations"] = []
            return

        stub = get_stub()
        members = instance.data.get("members", [])
        comp_settings = instance.data.get("comp_settings", {})
        comp_members = instance.data.get("comp_members", [])

        current_file = instance.context.data.get("currentFile", "")
        if not current_file:
            self.log.error("No current file for multi-comp render")
            instance.data["representations"] = []
            return

        work_dir = os.path.normpath(os.path.dirname(current_file))
        render_dir = os.path.join(work_dir, "render").replace("\\", "/")
        product_name = instance.data.get("productName", "renderMain")
        version = instance.data.get("version") or instance.context.data.get("version", 1)
        version_str = "v{:03d}".format(version)
        base_dir = os.path.join(
            render_dir,
            "{}_{}".format(product_name, version_str)
        ).replace("\\", "/")

        os.makedirs(base_dir, exist_ok=True)
        stub.set_render_path(path=base_dir, item_id=rq_item_id)

        pre_render_files = {}
        for root, dirs, files in os.walk(base_dir):
            pre_render_files[root] = set(files)

        render_start = time.time()
        stub.render(rq_item_id, timeout=600)
        self.log.info("Render completed for multi-comp RQ item %s", rq_item_id)

        subdir_to_files = {}
        for root, _dirs, files in os.walk(base_dir):
            for fname in files:
                _, ext = os.path.splitext(fname)
                if ext.lower() not in IMAGE_EXTS:
                    continue
                try:
                    fpath = os.path.join(root, fname)
                    mtime = os.path.getmtime(fpath)
                    # Include files created or overwritten by this render
                    if mtime < render_start - 2:
                        continue
                except OSError:
                    continue
                subdir_to_files.setdefault(root, []).append(fname)

        representations = []
        used_repre_names = set()
        creator_attributes = instance.data.get("creator_attributes", {})
        mark_review = creator_attributes.get("mark_for_review_mode", "first")
        comp_names = [m.get("comp_name", "") for m in comp_members]

        for idx, (output_dir, files) in enumerate(sorted(subdir_to_files.items())):
            if not files:
                continue
            subdir_name = os.path.basename(output_dir.rstrip(os.sep))
            # Use subdir_name as base - Cavalry outputs unique subdirs per comp
            # Fallback to comp_name only if subdir is generic (e.g. "0", "1")
            comp_name = comp_names[idx] if idx < len(comp_names) else ""
            if subdir_name and subdir_name not in ("0", "1", "2", "3"):
                base_name = subdir_name
            else:
                base_name = comp_name or subdir_name or "comp_{}".format(idx + 1)
            repre_name = _sanitize_comp_name(base_name)
            if repre_name in used_repre_names:
                repre_name = "{}_{}".format(repre_name, idx + 1)
            used_repre_names.add(repre_name)

            by_ext = {}
            for fname in sorted(files):
                ext = os.path.splitext(fname)[1][1:].lower()
                by_ext.setdefault(ext, []).append(fname)

            for ext, ext_files in by_ext.items():
                resulting_files = ext_files[0] if len(ext_files) == 1 else ext_files
                ext_repre = repre_name if len(by_ext) == 1 else "{}_{}".format(repre_name, ext)
                if ext_repre in used_repre_names:
                    ext_repre = "{}_{}".format(ext_repre, idx)
                used_repre_names.add(ext_repre)

                comp_id = members[idx] if idx < len(members) else None
                settings = comp_settings.get(comp_id, {}) if comp_id else {}
                repre_data = {
                    "name": ext_repre,
                    "ext": ext,
                    "files": resulting_files,
                    "stagingDir": output_dir,
                    "outputName": ext_repre,
                }
                if isinstance(resulting_files, list):
                    repre_data["frameStart"] = settings.get("frame_start")
                    repre_data["frameEnd"] = settings.get("frame_end")

                if mark_review == "first" and not representations:
                    repre_data["tags"] = ["review"]
                elif mark_review == "all":
                    repre_data["tags"] = ["review"]

                representations.append(repre_data)

        if not representations:
            self.log.warning(
                "No render output in %s (version=%s). "
                "Check that Cavalry wrote to the expected path.",
                base_dir, version_str,
            )
            # Fallback: Cavalry may have written to RQ item's filePath
            try:
                rq_dir = self._get_rq_item_output_dir(stub, rq_item_id)
                if rq_dir and os.path.isdir(rq_dir) and rq_dir != base_dir:
                    self.log.debug(
                        "No files in %s, trying RQ output dir: %s",
                        base_dir, rq_dir,
                    )
                    for root, _dirs, files in os.walk(rq_dir):
                        for fname in files:
                            _, ext = os.path.splitext(fname)
                            if ext.lower() not in IMAGE_EXTS:
                                continue
                            try:
                                fpath = os.path.join(root, fname)
                                if os.path.getmtime(fpath) >= render_start - 2:
                                    subdir_to_files.setdefault(root, []).append(fname)
                            except OSError:
                                pass
                    for idx, (output_dir, files) in enumerate(sorted(subdir_to_files.items())):
                        if not files:
                            continue
                        subdir_name = os.path.basename(output_dir.rstrip(os.sep))
                        comp_name = comp_names[idx] if idx < len(comp_names) else ""
                        base_name = subdir_name if subdir_name and subdir_name not in ("0", "1", "2", "3") else comp_name or subdir_name or "comp_{}".format(idx + 1)
                        repre_name = _sanitize_comp_name(base_name)
                        if repre_name in used_repre_names:
                            repre_name = "{}_{}".format(repre_name, idx + 1)
                        used_repre_names.add(repre_name)
                        by_ext = {}
                        for fname in sorted(files):
                            ext = os.path.splitext(fname)[1][1:].lower()
                            by_ext.setdefault(ext, []).append(fname)
                        for ext, ext_files in by_ext.items():
                            resulting_files = ext_files[0] if len(ext_files) == 1 else ext_files
                            ext_repre = repre_name if len(by_ext) == 1 else "{}_{}".format(repre_name, ext)
                            if ext_repre in used_repre_names:
                                ext_repre = "{}_{}".format(ext_repre, idx)
                            used_repre_names.add(ext_repre)
                            comp_id = members[idx] if idx < len(members) else None
                            settings = comp_settings.get(comp_id, {}) if comp_id else {}
                            repre_data = {"name": ext_repre, "ext": ext, "files": resulting_files, "stagingDir": output_dir, "outputName": ext_repre}
                            if isinstance(resulting_files, list):
                                repre_data["frameStart"] = settings.get("frame_start")
                                repre_data["frameEnd"] = settings.get("frame_end")
                            if mark_review == "first" and not representations:
                                repre_data["tags"] = ["review"]
                            elif mark_review == "all":
                                repre_data["tags"] = ["review"]
                            representations.append(repre_data)
            except Exception as exc:
                self.log.debug("Fallback RQ dir check failed: %s", exc)

        instance.data["representations"] = representations
        if representations:
            instance.data["stagingDir"] = base_dir

        self.log.info(
            "Collected %d representation(s) from multi-comp render",
            len(representations),
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

    def _find_new_files(self, pre_render_files, render_start):
        """Find files that appeared or were modified after render started."""
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

        return None, []
