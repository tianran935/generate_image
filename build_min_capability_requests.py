from __future__ import annotations

import runpy
import sys
from pathlib import Path

from experiments.build_min_capability_requests import *  # noqa: F401,F403

TARGET = Path(__file__).resolve().parent / "experiments" / "build_min_capability_requests.py"

if __name__ == "__main__":
    sys.path.insert(0, str(TARGET.parent))
    runpy.run_path(str(TARGET), run_name="__main__")
