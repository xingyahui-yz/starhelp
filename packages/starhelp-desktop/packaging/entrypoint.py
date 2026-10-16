import os
import sys

_dll_directories = []
if sys.platform == "win32" and getattr(sys, "frozen", False):
    # PyInstaller stores Qt and Shiboken DLLs in package subdirectories. Keep these
    # Windows DLL search handles alive before importing PySide6 from the PYZ archive.
    for package_dir in ("PySide6", "shiboken6"):
        path = os.path.join(sys._MEIPASS, package_dir)
        if os.path.isdir(path):
            _dll_directories.append(os.add_dll_directory(path))

from starhelp_desktop.__main__ import main

raise SystemExit(main())
