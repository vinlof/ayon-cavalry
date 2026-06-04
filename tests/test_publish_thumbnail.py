"""Tests for generic Cavalry publish thumbnail tagging."""

from __future__ import annotations

from ayon_cavalry.api.publish_thumbnail import (
    NEED_THUMBNAIL_TAG,
    pick_thumbnail_representation,
    tag_need_thumbnail,
)


def _repre(name: str, **kwargs):
    data = {"name": name, "ext": name, "files": "out.{}".format(name)}
    data.update(kwargs)
    return data


def test_pick_thumbnail_representation_prefers_png_over_exr():
    representations = [_repre("exr"), _repre("png")]
    chosen = pick_thumbnail_representation(representations)
    assert chosen is not None
    assert chosen["name"] == "png"


def test_pick_thumbnail_representation_prefers_jpeg_over_exr():
    representations = [_repre("exr"), _repre("jpeg")]
    chosen = pick_thumbnail_representation(representations)
    assert chosen is not None
    assert chosen["name"] == "jpeg"


def test_pick_thumbnail_representation_skips_existing_thumbnail_rep():
    representations = [
        _repre("thumbnail", thumbnail=True),
        _repre("exr"),
    ]
    chosen = pick_thumbnail_representation(representations)
    assert chosen is not None
    assert chosen["name"] == "exr"


def test_tag_need_thumbnail_adds_tag_once():
    representations = [_repre("exr"), _repre("png")]
    name = tag_need_thumbnail(representations)
    assert name == "png"
    assert NEED_THUMBNAIL_TAG in representations[1]["tags"]
    assert "tags" not in representations[0]

    name_again = tag_need_thumbnail(representations)
    assert name_again == "png"
    assert representations[1]["tags"].count(NEED_THUMBNAIL_TAG) == 1


def test_tag_need_thumbnail_merges_with_existing_tags():
    representations = [_repre("png", tags=["review"])]
    tag_need_thumbnail(representations)
    assert representations[0]["tags"] == ["review", NEED_THUMBNAIL_TAG]


def test_tag_need_thumbnail_returns_none_for_empty_list():
    assert tag_need_thumbnail([]) is None
