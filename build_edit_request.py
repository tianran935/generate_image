from __future__ import annotations

import runpy
import sys
from pathlib import Path

from core.build_edit_request import *  # noqa: F401,F403

TARGET = Path(__file__).resolve().parent / "core" / "build_edit_request.py"

if __name__ == "__main__":
    sys.path.insert(0, str(TARGET.parent))
    runpy.run_path(str(TARGET), run_name="__main__")
