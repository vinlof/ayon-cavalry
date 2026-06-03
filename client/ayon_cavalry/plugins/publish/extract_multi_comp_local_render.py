"""Extract local render from Cavalry for multi-comp instances.

Renders the publish instance's existing Render Queue item once (the same
item created in the UI when you added the render product). Output paths
come from that RQ item and Cavalry — not invented version folders under work/.

Collects new files under the RQ path / work/.../render and maps them to
compositions by folder or file name.
"""

import os
import re
import json
import time

MANIFEST_NAME = ".ayon_render_manifest.jsonl"

from ayon_core.pipeline import publish

from ayon_cavalry.api import get_stub
from ayon_cavalry.api.publish_progress import (
    report_multi_comp_render_progress,
    report_multi_comp_status,
)

IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".exr", ".tiff", ".tif",
    ".tga", ".bmp", ".mp4", ".mov", ".avi", ".svg",
}


def _safe_listdir(directory):
    """List directory entries; skip paths Windows denies."""
    try:
        return os.listdir(directory)
    except OSError:
        return []


def _sanitize_comp_name(name):
    """Sanitize comp name for representation and filesystem."""
    sanitized = re.sub(r"[^\w\-]", "_", str(name)).strip("_")
    return sanitized or "comp"


class ExtractMultiCompLocalRender(publish.Extractor):
    """Render multi-comp RQ item once and collect outputs per composition."""

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
        comp_settings = instance.data.get("comp_settings", {})
        comp_members = instance.data.get("comp_members", [])
        members = instance.data.get("members", [])
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
        rq_output_dir = self._get_rq_item_output_dir(stub, rq_item_id)

        candidate_dirs = self._build_collect_roots(
            work_dir, render_dir, rq_output_dir
        )
        if not candidate_dirs:
            self.log.error(
                "No render output directory on RQ item %s. "
                "Set Path in Render Manager before publishing.",
                rq_item_id,
            )
            instance.data["representations"] = []
            return

        self.log.info(
            "Multi-comp render using RQ item %s. Collecting under: %s",
            rq_item_id,
            ", ".join(candidate_dirs),
        )

        pre_render_files = {}
        for directory in candidate_dirs:
            if os.path.isdir(directory):
                pre_render_files[directory] = set(_safe_listdir(directory))

        creator_attributes = instance.data.get("creator_attributes", {})
        mark_review = creator_attributes.get("mark_for_review_mode", "first")
        total_comps = len(comp_members)

        # Deterministic mapping: ask Cavalry to record each render's exact
        # composition + resolved path via a Post-Render Script manifest.
        manifest_dir = rq_output_dir or render_dir
        manifest_path = os.path.join(manifest_dir, MANIFEST_NAME)
        self._remove_manifest(manifest_path)
        manifest_enabled = False
        try:
            manifest_enabled = stub.prepare_multi_comp_manifest(
                rq_item_id, manifest_path.replace("\\", "/")
            )
        except Exception as exc:
            self.log.warning("Could not attach render manifest script: %s", exc)

        self.label = report_multi_comp_status(
            "rendering {} comp(s)…".format(total_comps)
        )

        render_start = time.time()
        render_result = self._render_with_progress(
            stub, rq_item_id, manifest_path, manifest_enabled, total_comps
        )
        self.log.info(
            "Render completed for multi-comp RQ item %s (%d targets)",
            rq_item_id,
            total_comps,
        )

        # Clear the script so it is not baked into the saved workfile.
        if manifest_enabled:
            try:
                stub.prepare_multi_comp_manifest(rq_item_id, "")
            except Exception:
                pass

        manifest_map = self._read_manifest(manifest_path)
        if manifest_map:
            self.log.info(
                "Render manifest mapped %d composition(s) to exact files",
                len(manifest_map),
            )

        if render_result:
            for directory in self._dirs_from_render_result(render_result):
                if directory and os.path.isdir(directory):
                    if directory not in pre_render_files:
                        pre_render_files[directory] = set(_safe_listdir(directory))

        comp_outputs = self._group_new_files_by_comp(
            comp_members,
            comp_settings,
            candidate_dirs,
            pre_render_files,
            render_start,
        )

        representations = []
        used_repre_names = set()
        for idx, comp_member in enumerate(comp_members):
            self.label = report_multi_comp_render_progress(
                idx + 1, total_comps
            )
            comp_id = comp_member.get("comp_id") or (
                members[idx] if idx < len(members) else None
            )
            comp_name = comp_member.get("comp_name", "")
            if not comp_name and comp_id:
                comp_name = comp_settings.get(comp_id, {}).get("name", "")

            subdir_name = _sanitize_comp_name(comp_name) or "comp_{}".format(
                idx + 1
            )

            # Prefer the exact files Cavalry reported for this composition;
            # fall back to the folder/name heuristic only if the manifest
            # has no usable entry for it.
            output_dir, files = self._files_from_manifest(
                manifest_map, comp_id, comp_name
            )
            if not files:
                output_dir, files = comp_outputs.get(subdir_name, (None, []))
            if not files:
                self.log.warning(
                    "No render output matched comp %s under %s",
                    comp_name or comp_id,
                    candidate_dirs,
                )
                continue

            representations.extend(
                self._build_representations_for_files(
                    files=files,
                    output_dir=output_dir,
                    base_name=subdir_name,
                    comp_id=comp_id,
                    comp_settings=comp_settings,
                    mark_review=mark_review,
                    used_repre_names=used_repre_names,
                    idx=idx,
                    has_existing_representations=bool(representations),
                )
            )

        instance.data["representations"] = representations
        if representations:
            staging = rq_output_dir or render_dir
            instance.data["stagingDir"] = staging

        self.log.info(
            "Collected %d representation(s) from multi-comp render",
            len(representations),
        )

    def _build_collect_roots(self, work_dir, render_dir, rq_output_dir):
        """Directories to scan for output: the RQ item's path and work/.../render."""
        dirs = []
        for directory in (rq_output_dir, render_dir):
            if not directory:
                continue
            normalized = os.path.normpath(directory)
            if normalized not in dirs:
                dirs.append(normalized)
        return dirs

    def _group_new_files_by_comp(
        self,
        comp_members,
        comp_settings,
        candidate_dirs,
        pre_render_files,
        render_start,
    ):
        """Map new render files to comps by sanitized name in path."""
        comp_keys = []
        for idx, comp_member in enumerate(comp_members):
            comp_name = comp_member.get("comp_name", "")
            comp_id = comp_member.get("comp_id")
            if not comp_name and comp_id:
                comp_name = comp_settings.get(comp_id, {}).get("name", "")
            key = _sanitize_comp_name(comp_name) or "comp_{}".format(idx + 1)
            comp_keys.append((key, comp_name))

        grouped = {key: [] for key, _ in comp_keys}

        for directory in candidate_dirs:
            for root, _dirnames, filenames in self._safe_walk(directory):
                for fname in filenames:
                    _, ext = os.path.splitext(fname)
                    if ext.lower() not in IMAGE_EXTS:
                        continue
                    fpath = os.path.join(root, fname)
                    if not self._is_new_render_file(
                        fpath, directory, pre_render_files, render_start
                    ):
                        continue

                    rel = os.path.relpath(root, directory)
                    folder_hay = (
                        "" if rel in (".", "") else rel.replace("\\", "/").lower()
                    )
                    fname_hay = fname.lower()

                    matched_key = self._match_comp_key(
                        comp_keys, folder_hay, fname_hay
                    )
                    if matched_key:
                        grouped[matched_key].append((root, fname))

        result = {}
        for key, _ in comp_keys:
            entries = grouped.get(key) or []
            if not entries:
                result[key] = (None, [])
                continue
            by_dir = {}
            for root, fname in entries:
                by_dir.setdefault(root, []).append(fname)
            best_root = max(by_dir.keys(), key=lambda r: len(by_dir[r]))
            result[key] = (best_root, sorted(by_dir[best_root]))
        return result

    def _render_with_progress(
        self, stub, rq_item_id, manifest_path, manifest_enabled, total_comps
    ):
        """Render the multi-comp item, refreshing (N/Total) while it runs.

        The render is a single blocking call on Cavalry's side, so we dispatch
        it without blocking and poll the manifest (one line appended per comp
        by the Post-Render Script) to advance the publisher overlay. Falls back
        to a plain blocking render if the async path is unavailable.
        """
        render_timeout = 3600
        poll_interval = 0.5

        if not manifest_enabled or not hasattr(stub, "render_async"):
            return stub.render(rq_item_id, timeout=render_timeout)

        try:
            cmd_id, event = stub.render_async(rq_item_id)
        except Exception as exc:
            self.log.warning(
                "Async render unavailable (%s); falling back to blocking.", exc
            )
            return stub.render(rq_item_id, timeout=render_timeout)

        deadline = time.time() + render_timeout
        last_reported = -1
        while not event.wait(poll_interval):
            done = self._count_manifest_entries(manifest_path)
            if 0 < done != last_reported:
                self.label = report_multi_comp_render_progress(
                    min(done, total_comps), total_comps
                )
                last_reported = done
            if time.time() > deadline:
                self.log.warning(
                    "Render exceeded %ss; stopping progress poll.",
                    render_timeout,
                )
                break

        # Render finished: flush the counter to the full total.
        self.label = report_multi_comp_render_progress(total_comps, total_comps)
        return stub.get_command_result(cmd_id)

    def _count_manifest_entries(self, manifest_path):
        """Count completed renders recorded in the manifest so far."""
        if not manifest_path or not os.path.isfile(manifest_path):
            return 0
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                return sum(1 for line in handle if line.strip())
        except OSError:
            return 0

    def _remove_manifest(self, manifest_path):
        """Delete a stale manifest from a previous publish (best-effort)."""
        try:
            if manifest_path and os.path.isfile(manifest_path):
                os.remove(manifest_path)
        except OSError:
            pass

    def _read_manifest(self, manifest_path):
        """Parse the Post-Render manifest into ``{comp_id: [abs_path, ...]}``.

        Each line is one JSON object emitted by the post-render script with
        ``comp`` (a composition layer id, or list of ids) and ``path`` (the
        resolved output file). Returns an empty dict when no manifest exists.
        """
        result = {}
        if not manifest_path or not os.path.isfile(manifest_path):
            return result
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError:
            return result

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            path = entry.get("path")
            if not path:
                continue
            comp = entry.get("comp")
            comps = comp if isinstance(comp, list) else [comp]
            norm_path = os.path.normpath(path)
            for comp_id in comps:
                if comp_id:
                    result.setdefault(str(comp_id), []).append(norm_path)
        return result

    def _files_from_manifest(self, manifest_map, comp_id, comp_name):
        """Return ``(output_dir, [filenames])`` recorded for a composition.

        Matches on the composition layer id first, then on the comp name as a
        fallback. Only files that actually exist on disk are returned, so a
        stale manifest entry cleanly degrades to the heuristic path.
        """
        if not manifest_map:
            return None, []

        paths = []
        if comp_id and str(comp_id) in manifest_map:
            paths = manifest_map[str(comp_id)]
        elif comp_name and comp_name in manifest_map:
            paths = manifest_map[comp_name]

        existing = [p for p in paths if os.path.isfile(p)]
        if not existing:
            return None, []

        output_dir = os.path.dirname(existing[0])
        files = sorted({os.path.basename(p) for p in existing})
        return output_dir, files

    def _match_comp_key(self, comp_keys, folder_hay, fname_hay):
        """Map a rendered file to a comp.

        Cavalry writes a correct per-comp *subfolder* but may reuse the same
        *file name* for every target, so the folder is the reliable signal.
        Match the folder first; only fall back to the file name when no comp
        subfolder is present (flat output).
        """
        if folder_hay:
            for key, comp_name in comp_keys:
                if key.lower() in folder_hay:
                    return key
                if comp_name and comp_name.lower() in folder_hay:
                    return key

        for key, comp_name in comp_keys:
            if key.lower() in fname_hay:
                return key
            if comp_name and comp_name.lower() in fname_hay:
                return key

        if len(comp_keys) == 1:
            return comp_keys[0][0]
        return None

    def _safe_walk(self, directory):
        """os.walk that skips unreadable directories."""
        try:
            for item in os.walk(directory):
                yield item
        except OSError:
            return

    def _is_new_render_file(
        self, fpath, snapshot_root, pre_render_files, render_start
    ):
        """True if file is new since render started."""
        fname = os.path.basename(fpath)
        try:
            mtime = os.path.getmtime(fpath)
        except OSError:
            return False

        if mtime < render_start - 2:
            return False

        old = pre_render_files.get(snapshot_root, set())
        if fname in old:
            try:
                if mtime >= render_start - 2:
                    return True
            except OSError:
                pass
            return False
        return True

    def _dirs_from_render_result(self, render_result):
        """Extract directory candidates from a Cavalry render command result."""
        if not isinstance(render_result, dict):
            return []

        dirs = []
        item_attrs = render_result.get("item_attrs", {})

        file_path = item_attrs.get("filePath")
        if file_path and isinstance(file_path, str):
            parent = os.path.dirname(file_path) or file_path
            dirs.append(os.path.normpath(parent))
        elif isinstance(file_path, dict) and file_path.get("value"):
            value = str(file_path["value"])
            dirs.append(os.path.normpath(os.path.dirname(value) or value))

        render_path = render_result.get("render_path", "")
        if render_path:
            dirs.append(os.path.normpath(render_path))

        scene_path = render_result.get("scene_path", "")
        if scene_path:
            scene_dir = os.path.normpath(os.path.dirname(scene_path))
            if scene_dir:
                dirs.append(scene_dir)

        seen = set()
        unique = []
        for directory in dirs:
            if directory and directory not in seen:
                seen.add(directory)
                unique.append(directory)
        return unique

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
        """Directory from the RQ item Path / filePath (as configured in Cavalry)."""
        try:
            info = stub.get_render_queue_item_info(rq_item_id)
            attrs = info.get("attributes", {})
            file_path = attrs.get("filePath")
            if file_path and isinstance(file_path, str):
                return self._path_to_search_dir(file_path)
            if isinstance(file_path, dict) and "value" in file_path:
                return self._path_to_search_dir(file_path["value"])
        except Exception:
            pass
        return None

    def _path_to_search_dir(self, path):
        """Return a directory to search for rendered files."""
        if not path:
            return None
        normalized = os.path.normpath(path)
        if os.path.isdir(normalized):
            return normalized
        parent = os.path.dirname(normalized)
        return parent or normalized
