from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_PREFIX = datetime.now().strftime("%Y%m%d_%H%M%S")
GENERATE_REQUEST = ROOT / "output" / f"{RUN_PREFIX}_生图_price_only_请求.json"
GENERATE_IMAGE = ROOT / "output" / f"{RUN_PREFIX}_生图_price_only.png"
EDIT_SOURCE_REQUEST = ROOT / "output" / f"{RUN_PREFIX}_改图_price_only_源请求.json"
EDIT_REQUEST = ROOT / "output" / f"{RUN_PREFIX}_改图_price_only_请求.json"
EDIT_IMAGE = ROOT / "output" / f"{RUN_PREFIX}_改图_price_only.png"


def as_float(value: Any) -> float | None:
    try:
        return float(str(value).replace("$", ""))
    except (TypeError, ValueError):
        return None


def format_price(value: float) -> str:
    return f"${value:.2f}"


def build_price_only_edit_request(input_image: Path, base_request: Path, output_file: Path, seed: int) -> None:
    rng = random.Random(seed)
    payload = json.loads(base_request.read_text(encoding="utf-8"))
    edited_skus = []
    for sku in payload["skus"]:
        edited = dict(sku)
        edited.pop("tags", None)
        base_price = as_float(edited.get("base_price", edited.get("price"))) or 3.99
        edited["price"] = format_price(base_price * rng.lognormvariate(0, 0.3))
        edited_skus.append(edited)

    payload["mode"] = "edit"
    payload["input_image"] = str(input_image)
    payload["notes"] = (
        "Keep the original shelf, camera angle, lighting, product identities, background, positions, "
        "promotion labels, sizes, package appearances, and product facings unchanged. Only modify shelf price labels."
    )
    payload["skus"] = edited_skus
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, cwd=ROOT.parent, text=True, capture_output=True)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    print(result.stdout)


def assert_only_prices_changed(generate_request: Path, edit_request: Path) -> None:
    generate = json.loads(generate_request.read_text(encoding="utf-8"))
    edit = json.loads(edit_request.read_text(encoding="utf-8"))
    stable_keys = [
        "sku_id",
        "item",
        "category_id",
        "category_name",
        "base_price",
        "promotion",
        "bestseller_badge",
        "size",
        "position",
        "product_image",
    ]
    for generated_sku, edited_sku in zip(generate["skus"], edit["skus"], strict=True):
        for key in stable_keys:
            assert generated_sku.get(key) == edited_sku.get(key), (key, generated_sku, edited_sku)
        assert generated_sku["price"] != edited_sku["price"], (generated_sku["sku_id"], generated_sku["price"])


def main() -> None:
    if not os.getenv("OPENROUTER_API_KEY"):
        raise RuntimeError("OPENROUTER_API_KEY is not set.")

    run(
        [
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
            "2401",
            "--product-image-dir",
            "pic_reference",
            "--request-output-file",
            str(GENERATE_REQUEST),
            "--output-file",
            str(GENERATE_IMAGE),
            "--timeout-seconds",
            "600",
        ]
    )

    build_price_only_edit_request(
        input_image=GENERATE_IMAGE,
        base_request=GENERATE_REQUEST,
        output_file=EDIT_SOURCE_REQUEST,
        seed=2402,
    )

    run(
        [
            sys.executable,
            str(ROOT / "openrouter_shelf_image.py"),
            "--request-file",
            str(EDIT_SOURCE_REQUEST),
            "--product-image-dir",
            "pic_reference",
            "--request-output-file",
            str(EDIT_REQUEST),
            "--output-file",
            str(EDIT_IMAGE),
            "--timeout-seconds",
            "600",
        ]
    )

    assert_only_prices_changed(GENERATE_REQUEST, EDIT_REQUEST)
    print(
        json.dumps(
            {
                "generate_image": str(GENERATE_IMAGE),
                "edit_image": str(EDIT_IMAGE),
                "generate_request": str(GENERATE_REQUEST),
                "edit_request": str(EDIT_REQUEST),
                "only_prices_changed": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
