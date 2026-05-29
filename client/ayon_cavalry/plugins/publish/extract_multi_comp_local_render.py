"""Extract local render from Cavalry for multi-comp instances.

Renders each composition sequentially so the publisher can show per-comp
progress. Collects outputs from comp-specific subdirectories and builds
one representation per comp/output location.
"""

import os
import re
import time

from ayon_core.pipeline import publish

from ayon_cavalry.api import get_stub
from ayon_cavalry.api.publish_progress import report_multi_comp_render_progress

IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".exr", ".tiff", ".tif",
    ".tga", ".bmp", ".mp4", ".mov", ".avi", ".svg",
}


def _sanitize_comp_name(name):
    """Sanitize comp name for representation and filesystem."""
    sanitized = re.sub(r"[^\w\-]", "_", str(name)).strip("_")
    return sanitized or "comp"


class ExtractMultiCompLocalRender(publish.Extractor):
    """Render multi-comp instance one comp at a time and collect outputs."""

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
        if not comp_members and members:
            comp_members = [
                {"comp_id": comp_id, "comp_name": ""}
                for comp_id in members
            ]

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

        creator_attributes = instance.data.get("creator_attributes", {})
        mark_review = creator_attributes.get("mark_for_review_mode", "first")
        total_comps = len(comp_members)

        representations = []
        used_repre_names = set()

        for idx, comp_member in enumerate(comp_members):
            comp_index = idx + 1
            comp_id = comp_member.get("comp_id") or (
                members[idx] if idx < len(members) else None
            )
            comp_name = comp_member.get("comp_name", "")
            if not comp_name and comp_id:
                comp_name = comp_settings.get(comp_id, {}).get("name", "")

            self.label = report_multi_comp_render_progress(
                comp_index, total_comps
            )

            subdir_name = _sanitize_comp_name(comp_name) or "comp_{}".format(comp_index)
            comp_output_dir = os.path.join(base_dir, subdir_name).replace("\\", "/")
            os.makedirs(comp_output_dir, exist_ok=True)

            if not comp_id:
                self.log.warning(
                    "Skipping comp %d/%d: missing comp id",
                    comp_index,
                    total_comps,
                )
                continue

            temp_rq_id = stub.add_render_queue_item(comp_id)
            stub.set_render_path(path=comp_output_dir, item_id=temp_rq_id)

            render_start = time.time()
            stub.render(temp_rq_id, timeout=600)
            self.log.info(
                "Render completed for comp %s (%d/%d)",
                comp_name or comp_id,
                comp_index,
                total_comps,
            )

            files = self._collect_new_render_files(comp_output_dir, render_start)
            if not files:
                self.log.warning(
                    "No render output for comp %s in %s",
                    comp_name or comp_id,
                    comp_output_dir,
                )
                continue

            comp_representations = self._build_representations_for_files(
                files=files,
                output_dir=comp_output_dir,
                base_name=subdir_name,
                comp_id=comp_id,
                comp_settings=comp_settings,
                mark_review=mark_review,
                used_repre_names=used_repre_names,
                idx=idx,
                has_existing_representations=bool(representations),
            )
            representations.extend(comp_representations)

        if not representations:
            self.log.warning(
                "No render output in %s (version=%s). "
                "Check that Cavalry wrote to the expected path.",
                base_dir,
                version_str,
            )
            render_start = time.time() - 2
            try:
                rq_dir = self._get_rq_item_output_dir(stub, rq_item_id)
                if rq_dir and os.path.isdir(rq_dir) and rq_dir != base_dir:
                    self.log.debug(
                        "No files in %s, trying RQ output dir: %s",
                        base_dir,
                        rq_dir,
                    )
                    subdir_to_files = {}
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

                    comp_names = [m.get("comp_name", "") for m in comp_members]
                    for fallback_idx, (output_dir, files) in enumerate(
                        sorted(subdir_to_files.items())
                    ):
                        if not files:
                            continue
                        subdir_name = os.path.basename(output_dir.rstrip(os.sep))
                        comp_name = (
                            comp_names[fallback_idx]
                            if fallback_idx < len(comp_names)
                            else ""
                        )
                        if subdir_name and subdir_name not in ("0", "1", "2", "3"):
                            base_name = subdir_name
                        else:
                            base_name = (
                                comp_name
                                or subdir_name
                                or "comp_{}".format(fallback_idx + 1)
                            )
                        comp_id = (
                            members[fallback_idx]
                            if fallback_idx < len(members)
                            else None
                        )
                        representations.extend(
                            self._build_representations_for_files(
                                files=files,
                                output_dir=output_dir,
                                base_name=base_name,
                                comp_id=comp_id,
                                comp_settings=comp_settings,
                                mark_review=mark_review,
                                used_repre_names=used_repre_names,
                                idx=fallback_idx,
                                has_existing_representations=bool(representations),
                            )
                        )
            except Exception as exc:
                self.log.debug("Fallback RQ dir check failed: %s", exc)

        instance.data["representations"] = representations
        if representations:
            instance.data["stagingDir"] = base_dir

        self.log.info(
            "Collected %d representation(s) from multi-comp render",
            len(representations),
        )

    def _collect_new_render_files(self, output_dir, render_start):
        """Collect image/video files created or updated during a render."""
        if not os.path.isdir(output_dir):
            return []

        files = []
        for fname in os.listdir(output_dir):
            _, ext = os.path.splitext(fname)
            if ext.lower() not in IMAGE_EXTS:
                continue
            fpath = os.path.join(output_dir, fname)
            try:
                if os.path.getmtime(fpath) < render_start - 2:
                    continue
            except OSError:
                continue
            files.append(fname)
        return sorted(files)

    def _build_representations_for_files(
        self,
        files,
        output_dir,
        base_name,
        comp_id,
        comp_settings,
        mark_review,
        used_repre_names,
        idx,
        has_existing_representations,
    ):
        """Build representation dicts from rendered files in one output dir."""
        representations = []
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
            ext_repre = (
                repre_name if len(by_ext) == 1 else "{}_{}".format(repre_name, ext)
            )
            if ext_repre in used_repre_names:
                ext_repre = "{}_{}".format(ext_repre, idx)
            used_repre_names.add(ext_repre)

            repre_data = {
                "name": ext_repre,
                "ext": ext,
                "files": resulting_files,
                "stagingDir": output_dir,
                "outputName": ext_repre,
            }

            if mark_review == "first" and not has_existing_representations:
                repre_data["tags"] = ["review"]
                has_existing_representations = True
            elif mark_review == "all":
                repre_data["tags"] = ["review"]

            representations.append(repre_data)

        return representations

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
