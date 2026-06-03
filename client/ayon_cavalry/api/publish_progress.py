"""Helpers for updating the AYON publisher UI during long-running publish steps."""

EXTRACT_MULTI_COMP_LABEL = "Extract Multi-Comp Local Render"


def format_multi_comp_render_label(comp_index, comp_total):
    """Build plugin label shown in the publisher progress overlay."""
    if comp_total <= 1:
        return EXTRACT_MULTI_COMP_LABEL
    return "{} ({}/{})".format(EXTRACT_MULTI_COMP_LABEL, comp_index, comp_total)


def report_multi_comp_render_progress(comp_index, comp_total):
    """Update publisher overlay with current comp progress.

    Returns:
        str: Plugin label that was emitted (for ``self.label`` sync).
    """
    plugin_label = format_multi_comp_render_label(comp_index, comp_total)
    if comp_total <= 1:
        return plugin_label

    _emit_publish_status(plugin_label=plugin_label)
    return plugin_label


def report_multi_comp_status(message):
    """Push a free-form status suffix to the publisher overlay.

    Used for phases that are not per-comp (e.g. the single batch render),
    so the window still shows activity instead of appearing frozen.

    Returns:
        str: Plugin label that was emitted (for ``self.label`` sync).
    """
    if message:
        plugin_label = "{} — {}".format(EXTRACT_MULTI_COMP_LABEL, message)
    else:
        plugin_label = EXTRACT_MULTI_COMP_LABEL
    _emit_publish_status(plugin_label=plugin_label)
    return plugin_label


def _emit_publish_status(plugin_label=None, instance_label=None):
    controller = _get_publisher_controller()
    if controller is None:
        return

    if plugin_label is not None:
        controller.emit_event(
            "publish.process.plugin.changed",
            {"plugin_label": plugin_label},
        )
    if instance_label is not None:
        controller.emit_event(
            "publish.process.instance.changed",
            {"instance_label": instance_label},
        )

    _process_qt_events()


def _get_publisher_controller():
    try:
        from ayon_core.tools.utils.host_tools import _SingletonPoint

        _SingletonPoint._create_helper()
        helper = _SingletonPoint.helper
        if helper is not None and helper._publisher_tool is not None:
            return helper._publisher_tool.controller
    except Exception:
        pass

    try:
        from ayon_core.tools.publisher.app import _WindowCache

        window = _WindowCache.window
        if window is not None:
            return window.controller
    except Exception:
        pass

    return None


def _process_qt_events():
    try:
        from qtpy import QtWidgets

        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.processEvents()
    except Exception:
        pass
