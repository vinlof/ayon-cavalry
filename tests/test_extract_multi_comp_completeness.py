"""A multi-comp render must not publish when any composition is short."""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import types
from pathlib import Path

import pytest


def _load_extractor():
    """Load the extractor without the rest of the AYON runtime."""
    client = Path(__file__).resolve().parents[1] / "client"
    stubbed = [
        "ayon_cavalry",
        "ayon_cavalry.api",
        "ayon_cavalry.api.publish_thumbnail",
        "ayon_cavalry.api.publish_progress",
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

    path = (
        client
        / "ayon_cavalry"
        / "plugins"
        / "publish"
        / "extract_multi_comp_local_render.py"
    )
    spec = importlib.util.spec_from_file_location(
        "extract_multi_comp_local_render", path
    )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        for key, module_obj in previous.items():
            if module_obj is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = module_obj
    module.PublishError = PublishError
    return module


extractor = _load_extractor()


def test_complete_when_every_comp_has_the_same_count():
    message = extractor.incomplete_comp_output_message([
        ("products_4x5_feed_SE", 18),
        ("products_9x16_story_SE", 18),
    ])
    assert message is None


def test_missing_and_short_comps_are_named():
    message = extractor.incomplete_comp_output_message([
        ("products_4x5_feed_SE", 18),
        ("products_9x16_story_FR", 3),
        ("products_9x16_story_NL", 0),
        ("products_9x16_story_BE", 0),
    ])
    assert "products_9x16_story_NL" in message
    assert "products_9x16_story_BE" in message
    assert "products_9x16_story_FR (3/18)" in message
    assert "refusing to publish a partial set" in message


def test_empty_member_list_is_incomplete():
    message = extractor.incomplete_comp_output_message([])
    assert "no outputs" in message


class _Event:
    def __init__(self, ready_after):
        self.ready_after = ready_after
        self.waits = 0

    def wait(self, timeout):
        self.waits += 1
        return self.waits >= self.ready_after


class _Stub:
    def __init__(self, event):
        self.event = event
        self.result_calls = []
        self.render_timeout = "unset"

    def render_async(self, item_id):
        return "cmd-1", self.event

    def get_command_result(self, cmd_id):
        self.result_calls.append((cmd_id, self.event.waits))
        return {"success": True}

    def render(self, item_id, timeout=30):
        self.render_timeout = timeout
        return {"success": True}


def test_progress_poll_waits_out_a_long_render():
    """The old 3600s poll published whatever files existed and moved on."""
    module = extractor
    clock = {"n": 0}

    def fake_time():
        clock["n"] += 1
        return 0 if clock["n"] == 1 else 10 ** 9

    original = module.time.time
    module.time.time = fake_time
    try:
        event = _Event(ready_after=3)
        stub = _Stub(event)
        plugin = module.ExtractMultiCompLocalRender()
        result = plugin._render_with_progress(
            stub, "renderQueueItem#8", "manifest.jsonl", True, 16
        )
    finally:
        module.time.time = original

    assert result == {"success": True}
    assert event.waits == 3
    assert stub.result_calls == [("cmd-1", 3)]


def test_blocking_render_has_no_hour_cap():
    plugin = extractor.ExtractMultiCompLocalRender()
    stub = _Stub(_Event(ready_after=1))
    plugin._render_with_progress(stub, "renderQueueItem#8", None, False, 16)
    assert stub.render_timeout is None


class _Instance:
    def __init__(self, data, current_file):
        self.data = data
        self.context = types.SimpleNamespace(data={"currentFile": current_file})


def _plugin(module, stub):
    plugin = module.ExtractMultiCompLocalRender()
    plugin.log = logging.getLogger("test-multi-comp")
    module.get_stub = lambda: stub
    return plugin


def test_partial_render_raises_before_representations_are_set(tmp_path):
    out_dir = tmp_path / "render"
    out_dir.mkdir()
    scene = tmp_path / "scene.cv"
    scene.write_text("", encoding="utf-8")
    for name in ("feed_SE_0.mp4", "feed_SE_1.mp4", "story_FR_0.mp4"):
        (out_dir / name).write_bytes(b"video")

    class Stub:
        def get_render_queue_item_info(self, item_id):
            return {"attributes": {"filePath": str(out_dir)}}

        def prepare_multi_comp_manifest(self, item_id, path):
            return True

    plugin = _plugin(extractor, Stub())

    def finish_render(stub, rq_item_id, manifest_path, enabled, total):
        lines = [
            {"comp": "comp-se", "path": str(out_dir / "feed_SE_0.mp4")},
            {"comp": "comp-se", "path": str(out_dir / "feed_SE_1.mp4")},
            {"comp": "comp-fr", "path": str(out_dir / "story_FR_0.mp4")},
        ]
        with open(manifest_path, "w", encoding="utf-8") as handle:
            for line in lines:
                handle.write(json.dumps(line) + "\n")
        return {"success": True}

    plugin._render_with_progress = finish_render
    instance = _Instance(
        {
            "creator_attributes": {"multi_comp": True},
            "__layer_id__": "renderQueueItem#8",
            "comp_settings": {},
            "comp_members": [
                {"comp_id": "comp-se", "comp_name": "products_4x5_feed_SE"},
                {"comp_id": "comp-fr", "comp_name": "products_9x16_story_FR"},
                {"comp_id": "comp-nl", "comp_name": "products_9x16_story_NL"},
            ],
        },
        str(scene),
    )

    with pytest.raises(extractor.PublishError) as raised:
        plugin.process(instance)

    assert "products_9x16_story_FR (1/2)" in str(raised.value)
    assert "products_9x16_story_NL" in str(raised.value)
    assert "representations" not in instance.data


def test_even_render_publishes_every_comp(tmp_path):
    out_dir = tmp_path / "render"
    out_dir.mkdir()
    scene = tmp_path / "scene.cv"
    scene.write_text("", encoding="utf-8")
    for name in ("feed_SE_0.mp4", "story_NL_0.mp4"):
        (out_dir / name).write_bytes(b"video")

    class Stub:
        def get_render_queue_item_info(self, item_id):
            return {"attributes": {"filePath": str(out_dir)}}

        def prepare_multi_comp_manifest(self, item_id, path):
            return True

    plugin = _plugin(extractor, Stub())

    def finish_render(stub, rq_item_id, manifest_path, enabled, total):
        lines = [
            {"comp": "comp-se", "path": str(out_dir / "feed_SE_0.mp4")},
            {"comp": "comp-nl", "path": str(out_dir / "story_NL_0.mp4")},
        ]
        with open(manifest_path, "w", encoding="utf-8") as handle:
            for line in lines:
                handle.write(json.dumps(line) + "\n")
        return {"success": True}

    plugin._render_with_progress = finish_render
    instance = _Instance(
        {
            "creator_attributes": {"multi_comp": True},
            "__layer_id__": "renderQueueItem#8",
            "comp_settings": {},
            "comp_members": [
                {"comp_id": "comp-se", "comp_name": "products_4x5_feed_SE"},
                {"comp_id": "comp-nl", "comp_name": "products_9x16_story_NL"},
            ],
        },
        str(scene),
    )

    plugin.process(instance)

    files = [repre["files"] for repre in instance.data["representations"]]
    assert files == ["feed_SE_0.mp4", "story_NL_0.mp4"]
