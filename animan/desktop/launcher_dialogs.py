"""Request OS file choosers (GTK/portal on Linux, Windows and Cocoa elsewhere)."""
from pathlib import Path
from PySide6.QtWidgets import QFileDialog


def choose_directory(parent, title, initial):
    initial = Path(initial)
    if not initial.is_dir():
        initial = Path.home()
    # Do not set DontUseNativeDialog: the platform helper owns selection/cancel.
    return QFileDialog.getExistingDirectory(parent, title, str(initial), QFileDialog.Option.ShowDirsOnly)


def save_file(parent, title, filename, pattern):
    result = QFileDialog.getSaveFileName(parent, title, str(Path.home() / filename), pattern)[0]
    if result and not Path(result).suffix:
        result += Path(filename).suffix
    return result
