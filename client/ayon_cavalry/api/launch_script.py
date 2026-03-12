"""Script wraps launch mechanism of Cavalry implementations.

Arguments passed to the script are passed to launch function in host
implementation. In all cases requires host app executable and may contain
workfile or others.
"""

import os
import sys

from ayon_cavalry.api.launch_logic import main as host_main

CURRENT_FILE = os.path.abspath(__file__)


def show_error_messagebox(title, message, detail_message=None):
    """Show error dialog and exit."""
    from qtpy import QtWidgets, QtCore
    from ayon_core import style

    app = QtWidgets.QApplication([])
    app.setStyleSheet(style.load_stylesheet())

    msgbox = QtWidgets.QMessageBox()
    msgbox.setWindowTitle(title)
    msgbox.setText(message)
    if detail_message:
        msgbox.setDetailedText(detail_message)

    msgbox.setWindowModality(QtCore.Qt.ApplicationModal)
    msgbox.show()

    sys.exit(app.exec_())


def on_invalid_args(script_not_found):
    title = "Invalid arguments"
    joined_args = ", ".join('"{}"'.format(arg) for arg in sys.argv)

    if script_not_found:
        submsg = "Could not find script path:\n\"{}\""
    else:
        submsg = "Expected Host executable after script path:\n\"{}\""

    message = (
        "BUG: Got invalid arguments so cannot launch Cavalry."
    )
    detail_message = (
        "Process was launched with arguments:\n{}\n\n{}".format(
            joined_args, submsg.format(CURRENT_FILE)
        )
    )
    show_error_messagebox(title, message, detail_message)


def main(argv):
    modified_current_file = CURRENT_FILE.replace("\\", "/").lower()

    sys_args = list(argv)
    after_script_idx = None

    for idx, item in enumerate(sys_args):
        if item.replace("\\", "/").lower() == modified_current_file:
            after_script_idx = idx + 1
            break

    launch_args = None
    if after_script_idx is not None:
        launch_args = sys_args[after_script_idx:]

    if launch_args:
        host_main(*launch_args)
    else:
        on_invalid_args(after_script_idx is None)


if __name__ == "__main__":
    main(sys.argv)
