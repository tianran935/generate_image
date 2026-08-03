from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_PREFIX = datetime.now().strftime("%Y%m%d_%H%M%S")
REQUEST_FILE = ROOT / "output" / f"{RUN_PREFIX}_生图_test_generate_请求.json"
IMAGE_FILE = ROOT / "output" / f"{RUN_PREFIX}_生图_test_generate.png"


def main() -> None:
    cmd = [
        sys.executable,
        str(ROOT / "openrouter_shelf_image.py"),
        "--mode",
        "generate",
        "--category",
        "TORTILLA CHIPS",
        "--sample-size",
        "8",
        "--sample-count",
        "1",
        "--seed",
        "42",
        "--request-output-file",
        str(REQUEST_FILE),
        "--output-file",
        str(IMAGE_FILE),
    ]

    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    print(result.stdout)

    request = json.loads(REQUEST_FILE.read_text(encoding="utf-8"))
    assert request["mode"] == "generate"
    assert request["layout"] == {"rows": 2, "cols": 4}
    assert len(request["skus"]) == 8
    assert {sku["position"]["row"] for sku in request["skus"]} == {1, 2}
    assert {sku["position"]["col"] for sku in request["skus"]} == {1, 2, 3, 4}
    assert {sku["bestseller_badge"] for sku in request["skus"]} == {"none"}

    assert IMAGE_FILE.exists() and IMAGE_FILE.stat().st_size > 0

    print(json.dumps({"request_file": str(REQUEST_FILE), "image_file": str(IMAGE_FILE)}, indent=2))


if __name__ == "__main__":
    main()
