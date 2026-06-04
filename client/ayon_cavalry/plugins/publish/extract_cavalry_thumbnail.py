"""Run ayon-core thumbnail extraction for Cavalry publish instances.

ayon-core's ``ExtractThumbnail`` plugin does not include ``cavalry`` in its
``hosts`` list, so ``need_thumbnail`` tags from render extractors are ignored
unless this host-specific plugin runs the same logic.

Settings are read from core ``ExtractThumbnail`` (this class name is not in
studio settings and would otherwise stay disabled with empty profiles).
"""

from ayon_core.pipeline.publish.lib import apply_plugin_settings_automatically
from ayon_core.plugins.publish.extract_thumbnail import ExtractThumbnail

_CORE_THUMBNAIL_SETTINGS_KEY = "ExtractThumbnail"


class ExtractCavalryThumbnail(ExtractThumbnail):
    """Extract version thumbnail for Cavalry ``render`` / ``render.local``."""

    label = "Extract Thumbnail"
    hosts = ["cavalry"]
    families = list(ExtractThumbnail.families) + ["render.local"]

    @classmethod
    def apply_settings(cls, project_settings):
        """Apply the same publish settings as ayon-core ``ExtractThumbnail``."""
        publish_settings = (
            project_settings.get("core", {}).get("publish", {})
        )
        plugin_settings = publish_settings.get(_CORE_THUMBNAIL_SETTINGS_KEY)
        if not plugin_settings:
            return

        apply_plugin_settings_automatically(cls, plugin_settings)

    def _is_review_instance(self, instance):
        # Version thumbnails use need_thumbnail; do not require review flag.
        if self._get_explicit_repres_for_thumbnail(instance):
            return True
        return super()._is_review_instance(instance)
