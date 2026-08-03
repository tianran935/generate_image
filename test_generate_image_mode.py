from __future__ import annotations

import runpy
import sys
from pathlib import Path

from checks.test_generate_image_mode import *  # noqa: F401,F403

TARGET = Path(__file__).resolve().parent / "checks" / "test_generate_image_mode.py"

if __name__ == "__main__":
    sys.path.insert(0, str(TARGET.parent))
    runpy.run_path(str(TARGET), run_name="__main__")
