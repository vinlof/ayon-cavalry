"""Generic helpers for Ayon version thumbnails on Cavalry publish."""

from __future__ import annotations

from typing import Any

THUMBNAIL_SOURCE_EXT_PRIORITY = (
    "png",
    "jpg",
    "jpeg",
    "mp4",
    "mov",
)

NEED_THUMBNAIL_TAG = "need_thumbnail"


def _normalize_ext(ext: str | None) -> str:
    return (ext or "").lower().lstrip(".")


def _is_thumbnail_representation(repre: dict[str, Any]) -> bool:
    if repre.get("thumbnail"):
        return True
    return _normalize_ext(repre.get("name")) == "thumbnail"


def _extension_sort_key(ext: str) -> tuple[int, int, str]:
    """Lower sort key = preferred thumbnail source."""
    normalized = _normalize_ext(ext)
    if normalized in THUMBNAIL_SOURCE_EXT_PRIORITY:
        return (0, THUMBNAIL_SOURCE_EXT_PRIORITY.index(normalized), normalized)
    if normalized == "exr":
        return (2, 0, normalized)
    return (1, 0, normalized)


def pick_thumbnail_representation(
    representations: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Pick one representation suitable for ayon-core thumbnail extraction."""
    candidates = [
        repre
        for repre in representations
        if not _is_thumbnail_representation(repre)
    ]
    if not candidates:
        return None

    return min(
        candidates,
        key=lambda repre: _extension_sort_key(
            repre.get("ext") or repre.get("name")
        ),
    )


def tag_need_thumbnail(representations: list[dict[str, Any]]) -> str | None:
    """Tag the best representation with ``need_thumbnail``.

    Returns the chosen representation name, or None if no candidate exists.
    """
    repre = pick_thumbnail_representation(representations)
    if repre is None:
        return None

    tags = list(repre.get("tags") or [])
    if NEED_THUMBNAIL_TAG not in tags:
        tags.append(NEED_THUMBNAIL_TAG)
        repre["tags"] = tags

    return repre.get("name")
