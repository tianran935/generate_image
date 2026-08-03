from __future__ import annotations

import copy
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
GENERATE_IMAGE_DIR = ROOT / "generate_image"
CORE_DIR = GENERATE_IMAGE_DIR / "core"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
PRODUCT_IMAGE_DIR = ROOT / "pic_reference"

sys.path.insert(0, str(CORE_DIR))

from openrouter_shelf_image import (  # noqa: E402
    attach_product_images_to_payload,
    build_messages,
    call_openrouter,
    extract_image_bytes,
    render_product_reference_thumbnail,
    save_request_payloads,
)
from shelf_sampling import build_generate_payload, sample_products  # noqa: E402


MODEL = "openai/gpt-5.4-image-2"
CATEGORY = "TORTILLA CHIPS"
SEED = 20260719


def build_base_payload() -> dict[str, Any]:
    sample = sample_products(
        categories=[CATEGORY],
        sample_size=8,
        sample_count=1,
        seed=SEED,
    )[0]
    payload = build_generate_payload(sample, seed=SEED)
    payload = attach_product_images_to_payload(
        payload=payload,
        product_image_dir=PRODUCT_IMAGE_DIR,
        allow_missing=False,
    )

    payload["style"] = "realistic complete supermarket shelf photograph"
    for sku in payload["skus"]:
        sku["promotion"] = "none"
        sku["bestseller_badge"] = "none"

    return payload


def condition_payload(base_payload: dict[str, Any], condition: str, eye_level_row: int) -> dict[str, Any]:
    payload = copy.deepcopy(base_payload)
    payload["eye_level_condition"] = condition
    payload["eye_level_row"] = eye_level_row
    non_eye_row = 1 if eye_level_row == 2 else 2
    payload["notes"] = (
        "Create a complete supermarket shelf scene, not cropped product cutouts. "
        "Show two clear target shelf rows with four target product columns per row, realistic shelf rails, "
        "price strips, shelf depth, aisle context, and neighboring filler products outside the target 2x4 grid. "
        "Keep every target SKU, price, promotion state, badge state, size, and grid position stable. "
        f"For this experimental condition, row {eye_level_row} is exactly at a typical adult shopper's eye level and "
        f"row {non_eye_row} is clearly not at eye level. Make the camera height, perspective, and visual salience reflect "
        "that shopper sightline naturally, but do not add any visible text, arrows, labels, or annotations saying eye level. "
        "The resulting image should be usable as a visual stimulus for a shopping-decision LLM experiment."
    )
    return payload


def save_json(path: Path, content: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_one(payload: dict[str, Any], output_file: Path, request_file: Path) -> dict[str, str]:
    thumbnail_file = render_product_reference_thumbnail(payload, output_file)
    if thumbnail_file:
        payload["product_reference_sheet"] = str(thumbnail_file)
    payload["reference_sheet_only"] = False
    save_request_payloads(request_file, [payload])

    if output_file.exists() and output_file.stat().st_size > 0:
        return {
            "condition": payload["eye_level_condition"],
            "eye_level_row": str(payload["eye_level_row"]),
            "image": str(output_file),
            "request": str(request_file),
            "product_reference_sheet": str(thumbnail_file) if thumbnail_file else "",
            "status": "skipped_existing_image",
        }

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")

    messages = build_messages(payload)
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            result = call_openrouter(
                api_key=api_key,
                model=MODEL,
                messages=messages,
                aspect_ratio="4:3",
                image_size="1K",
                timeout_seconds=600,
            )
            break
        except Exception as exc:
            last_error = exc
            print(f"{payload['eye_level_condition']} attempt {attempt} failed: {exc}", file=sys.stderr)
            if attempt < 3:
                time.sleep(10 * attempt)
    else:
        assert last_error is not None
        raise last_error

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(extract_image_bytes(result))

    return {
        "condition": payload["eye_level_condition"],
        "eye_level_row": str(payload["eye_level_row"]),
        "image": str(output_file),
        "request": str(request_file),
        "product_reference_sheet": str(thumbnail_file) if thumbnail_file else "",
        "status": "generated",
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base_payload = build_base_payload()
    save_json(OUTPUT_DIR / "base_payload.json", base_payload)

    conditions = [
        condition_payload(base_payload, "row1_eye_level", eye_level_row=1),
        condition_payload(base_payload, "row2_eye_level", eye_level_row=2),
    ]

    results = []
    for payload in conditions:
        condition = payload["eye_level_condition"]
        results.append(
            generate_one(
                payload=payload,
                output_file=OUTPUT_DIR / f"{condition}.png",
                request_file=OUTPUT_DIR / f"{condition}_request.json",
            )
        )

    save_json(OUTPUT_DIR / "results.json", results)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
