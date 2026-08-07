"""Point frozen builds at the bundled Tcl/Tk script libraries.

PyInstaller normally installs an equivalent runtime hook.  Some Windows
installations still let Tcl search only the default Python directories after
one-file extraction, so the application carries an explicit, private copy and
sets both paths before tkinter is imported.
"""

from __future__ import annotations

import os
import sys
import ctypes
from pathlib import Path


def _configure_tk_runtime() -> None:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if not bundle_root:
        return

    runtime_root = Path(bundle_root) / "tcl_runtime"
    tcl_library = runtime_root / "tcl8.6"
    tk_library = runtime_root / "tk8.6"

    if (tcl_library / "init.tcl").is_file():
        os.environ["TCL_LIBRARY"] = str(tcl_library)
    if (tk_library / "tk.tcl").is_file():
        os.environ["TK_LIBRARY"] = str(tk_library)

    extraction_parent = Path(bundle_root).parent
    if os.name == "nt" and extraction_parent.name == "LineDogDeskPetRuntime":
        try:
            attributes = ctypes.windll.kernel32.GetFileAttributesW(str(extraction_parent))
            if attributes != -1:
                ctypes.windll.kernel32.SetFileAttributesW(
                    str(extraction_parent), attributes | 0x02
                )
        except (AttributeError, OSError):
            pass


_configure_tk_runtime()
