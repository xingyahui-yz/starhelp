from __future__ import annotations

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        from .gui import create_window
    except ImportError as exc:
        sys.stderr.write(
            f"Desktop dependencies could not be loaded ({type(exc).__name__}: {exc}). "
            "Install this component with the [desktop] extra.\n"
        )
        return 2
    try:
        app = QApplication(sys.argv)
        window = create_window()
    except Exception as exc:
        QMessageBox.critical(None, "StarHelp could not start", str(exc))
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
