"""Use existing frames publishes files already on disk and does not render."""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
import types
from pathlib import Path

import pytest


def _load_modules():
    """Load the frame extractors without the rest of the AYON runtime."""
    client = Path(__file__).resolve().parents[1] / "client"
    publish_dir = client / "ayon_cavalry" / "plugins" / "publish"
    stubbed = [
        "ayon_cavalry",
        "ayon_cavalry.api",
        "ayon_cavalry.api.publish_thumbnail",
        "ayon_cavalry.api.publish_progress",
        "ayon_cavalry.plugins",
        "ayon_cavalry.plugins.publish",
        "ayon_core",
        "ayon_core.pipeline",
        "ayon_core.pipeline.publish",
    ]
    previous = {key: sys.modules.get(key) for key in stubbed}

    package = types.ModuleType("ayon_cavalry")
    package.__path__ = [str(client / "ayon_cavalry")]
    sys.modules["ayon_cavalry"] = package

    api = types.ModuleType("ayon_cavalry.api")
    api.get_stub = lambda: None
    package.api = api
    sys.modules["ayon_cavalry.api"] = api

    thumbnail = types.ModuleType("ayon_cavalry.api.publish_thumbnail")
    thumbnail.tag_need_thumbnail = lambda representations: None
    sys.modules["ayon_cavalry.api.publish_thumbnail"] = thumbnail

    progress = types.ModuleType("ayon_cavalry.api.publish_progress")
    progress.report_multi_comp_render_progress = (
        lambda done, total: "{}/{}".format(done, total)
    )
    progress.report_multi_comp_status = lambda text: text
    sys.modules["ayon_cavalry.api.publish_progress"] = progress

    plugins = types.ModuleType("ayon_cavalry.plugins")
    plugins.__path__ = [str(client / "ayon_cavalry" / "plugins")]
    sys.modules["ayon_cavalry.plugins"] = plugins
    publish_pkg = types.ModuleType("ayon_cavalry.plugins.publish")
    publish_pkg.__path__ = [str(publish_dir)]
    sys.modules["ayon_cavalry.plugins.publish"] = publish_pkg

    publish = types.ModuleType("ayon_core.pipeline.publish")

    class Extractor:
        order = 0.0

    class PublishError(Exception):
        def __init__(self, message, title=None, description=None, detail=None):
            super().__init__(message)
            self.message = message

    publish.Extractor = Extractor
    publish.PublishError = PublishError

    pipeline = types.ModuleType("ayon_core.pipeline")
    pipeline.publish = publish
    ayon_core = types.ModuleType("ayon_core")
    ayon_core.pipeline = pipeline
    sys.modules["ayon_core"] = ayon_core
    sys.modules["ayon_core.pipeline"] = pipeline
    sys.modules["ayon_core.pipeline.publish"] = publish

    def load(module_name, filename):
        path = publish_dir / filename
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    try:
        multi = load(
            "ayon_cavalry.plugins.publish.extract_multi_comp_local_render",
            "extract_multi_comp_local_render.py",
        )
        local = load(
            "ayon_cavalry.plugins.publish.extract_local_render",
            "extract_local_render.py",
        )
        frames = load(
            "ayon_cavalry.plugins.publish.extract_existing_frames",
            "extract_existing_frames.py",
        )
    finally:
        for key, module_obj in previous.items():
            if module_obj is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = module_obj

    frames.PublishError = PublishError
    return multi, local, frames


multi, _local, frames = _load_modules()


class _Stub:
    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.calls = []

    def get_render_queue_item_info(self, item_id):
        self.calls.append(("info", item_id))
        return {"attributes": {"filePath": self.output_dir}}

    def render(self, *args, **kwargs):
        raise AssertionError("existing frames must not render")

    def render_async(self, *args, **kwargs):
        raise AssertionError("existing frames must not render")

    def prepare_multi_comp_manifest(self, *args, **kwargs):
        raise AssertionError("existing frames must not attach a manifest script")


class _Instance:
    def __init__(self, data, current_file):
        self.data = data
        self.context = types.SimpleNamespace(data={"currentFile": current_file})


def _plugin(stub):
    multi.get_stub = lambda: stub
    frames.get_stub = lambda: stub
    plugin = frames.ExtractExistingFrames()
    plugin.log = logging.getLogger("test-existing-frames")
    return plugin


def _multi_instance(scene, members):
    return _Instance(
        {
            "creator_attributes": {"multi_comp": True},
            "__layer_id__": "renderQueueItem#8",
            "comp_settings": {},
            "comp_members": members,
        },
        str(scene),
    )


def test_manifest_is_published_without_rendering(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    scene = tmp_path / "scene.cv"
    scene.write_text("", encoding="utf-8")
    se = out_dir / "feed_SE_0.mp4"
    nl = out_dir / "story_NL_0.mp4"
    se.write_bytes(b"video")
    nl.write_bytes(b"video")
    manifest = out_dir / ".ayon_render_manifest.jsonl"
    lines = [
        {"comp": "comp-se", "path": str(se)},
        {"comp": "comp-nl", "path": str(nl)},
    ]
    manifest.write_text(
        "".join(json.dumps(line) + "\n" for line in lines),
        encoding="utf-8",
    )
    stub = _Stub(str(out_dir))
    plugin = _plugin(stub)
    instance = _multi_instance(
        scene,
        [
            {"comp_id": "comp-se", "comp_name": "products_4x5_feed_SE"},
            {"comp_id": "comp-nl", "comp_name": "products_9x16_story_NL"},
        ],
    )

    plugin.process(instance)

    files = [repre["files"] for repre in instance.data["representations"]]
    assert files == ["feed_SE_0.mp4", "story_NL_0.mp4"]
    assert manifest.is_file()
    assert stub.calls == [("info", "renderQueueItem#8")]


def test_disk_fallback_matches_comp_names_when_manifest_is_missing(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    scene = tmp_path / "scene.cv"
    scene.write_text("", encoding="utf-8")
    (out_dir / "products_4x5_feed_SE_0.mp4").write_bytes(b"video")
    (out_dir / "products_9x16_story_NL_0.mp4").write_bytes(b"video")
    plugin = _plugin(_Stub(str(out_dir)))
    instance = _multi_instance(
        scene,
        [
            {"comp_id": "comp-se", "comp_name": "products_4x5_feed_SE"},
            {"comp_id": "comp-nl", "comp_name": "products_9x16_story_NL"},
        ],
    )

    plugin.process(instance)

    files = sorted(
        repre["files"] for repre in instance.data["representations"]
    )
    assert files == [
        "products_4x5_feed_SE_0.mp4",
        "products_9x16_story_NL_0.mp4",
    ]


def test_partial_existing_set_is_refused(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    scene = tmp_path / "scene.cv"
    scene.write_text("", encoding="utf-8")
    for name in ("feed_SE_0.mp4", "feed_SE_1.mp4", "story_FR_0.mp4"):
        (out_dir / name).write_bytes(b"video")
    lines = [
        {"comp": "comp-se", "path": str(out_dir / "feed_SE_0.mp4")},
        {"comp": "comp-se", "path": str(out_dir / "feed_SE_1.mp4")},
        {"comp": "comp-fr", "path": str(out_dir / "story_FR_0.mp4")},
    ]
    (out_dir / ".ayon_render_manifest.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines),
        encoding="utf-8",
    )
    plugin = _plugin(_Stub(str(out_dir)))
    instance = _multi_instance(
        scene,
        [
            {"comp_id": "comp-se", "comp_name": "products_4x5_feed_SE"},
            {"comp_id": "comp-fr", "comp_name": "products_9x16_story_FR"},
            {"comp_id": "comp-nl", "comp_name": "products_9x16_story_NL"},
        ],
    )

    with pytest.raises(frames.PublishError) as raised:
        plugin.process(instance)

    assert "products_9x16_story_FR (1/2)" in str(raised.value)
    assert "products_9x16_story_NL" in str(raised.value)
    assert "representations" not in instance.data


def test_single_comp_publishes_files_already_in_the_output_folder(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "shot_0.mp4").write_bytes(b"video")
    (out_dir / "shot_1.mp4").write_bytes(b"video")
    (out_dir / "notes.txt").write_text("skip", encoding="utf-8")
    stub = _Stub(str(out_dir))
    plugin = _plugin(stub)
    instance = _Instance(
        {
            "creator_attributes": {"multi_comp": False},
            "__layer_id__": "renderQueueItem#1",
        },
        str(tmp_path / "scene.cv"),
    )

    plugin.process(instance)

    assert instance.data["representations"][0]["files"] == [
        "shot_0.mp4",
        "shot_1.mp4",
    ]
    assert stub.calls == [("info", "renderQueueItem#1")]


def test_latest_manifest_is_the_one_beside_the_version_folder(tmp_path):
    render = tmp_path / "render"
    version = render / "dpj_work_a_ads_v019"
    version.mkdir(parents=True)
    parent_manifest = render / ".ayon_render_manifest.jsonl"
    version_manifest = version / ".ayon_render_manifest.jsonl"
    parent_manifest.write_text('{"comp":"old","path":"a.mp4"}\n', encoding="utf-8")
    version_manifest.write_text(
        '{"comp":"products_4x5_feed_SE","path":"b.mp4"}\n',
        encoding="utf-8",
    )
    os.utime(parent_manifest, (1_000, 1_000))
    os.utime(version_manifest, (2_000, 2_000))

    helper = multi.ExtractMultiCompLocalRender()
    found = [os.path.normpath(path) for path in helper._latest_manifests(str(render))]

    assert found == [os.path.normpath(str(version_manifest))]
