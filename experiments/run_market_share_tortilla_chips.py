from __future__ import annotations

import argparse
import copy
import json
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "generate_image" / "core"
SCRIPT = ROOT / "generate_image" / "openrouter_shelf_image.py"
DEFAULT_ORIGINAL_IMAGE = ROOT / "generate_image" / "output" / "runs" / "原始参考.png"
DEFAULT_OUTPUT_ROOT = ROOT / "generate_image" / "output" / "runs" / "market_share" / "tortilla_chips"
MARKET_SHARE_CATEGORY = "TORTILLA CHIPS"
MARKET_SHARE_BESTSELLER_LABELS = ("BEST SELLER", "TOP PICK", "HOT")
SHOPPER_INSTRUCTION = "Choose one tortilla chips product you would buy from this shelf."

if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from openrouter_shelf_image import (  # noqa: E402
    DEFAULT_PRODUCT_IMAGE_DIR,
    attach_product_images_to_payload,
    find_product_image,
    list_product_images,
)
from shelf_sampling import (  # noqa: E402
    DEFAULT_CATALOG_FILE,
    build_edit_payload,
    build_generate_payload,
    load_catalog,
    positions_2x4,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and optionally generate tortilla chips market-share edit images.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--original-image", type=Path, default=DEFAULT_ORIGINAL_IMAGE)
    parser.add_argument("--tag-reference-image", type=Path, help="Optional reference image for realistic shelf-talker tag styling.")
    parser.add_argument("--catalog-file", type=Path, default=DEFAULT_CATALOG_FILE)
    parser.add_argument("--product-image-dir", type=Path, default=DEFAULT_PRODUCT_IMAGE_DIR)
    parser.add_argument("--sample-count", type=int, default=1)
    parser.add_argument("--sample-size", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    parser.add_argument("--attempts", type=int, default=4)
    parser.add_argument("--retry-delay-seconds", type=int, default=60)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--subprocess-timeout-seconds", type=int, default=780)
    parser.add_argument("--model")
    parser.add_argument("--aspect-ratio", default="4:3")
    parser.add_argument("--image-size", choices=["1K", "2K"], default="1K")
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rows_with_product_images(catalog_file: Path, product_image_dir: Path) -> list[dict[str, Any]]:
    product_images = list_product_images(product_image_dir)
    if not product_images:
        raise FileNotFoundError(f"No product reference images found in {product_image_dir}")

    rows = [row for row in load_catalog(catalog_file) if str(row.get("category_name")) == MARKET_SHARE_CATEGORY]
    eligible: list[dict[str, Any]] = []
    for row in rows:
        sku_like = {
            "sku_id": row.get("upc_id"),
            "upc_id": row.get("upc_id"),
            "item": row.get("upc_description"),
            "source_row": row,
        }
        if find_product_image(sku_like, product_images):
            eligible.append(row)
    return eligible


def sample_tortilla_products(args: argparse.Namespace) -> list[dict[str, Any]]:
    rng = random.Random(args.seed)
    rows = rows_with_product_images(args.catalog_file, args.product_image_dir)
    if len(rows) < args.sample_size:
        raise ValueError(
            f"{MARKET_SHARE_CATEGORY} has only {len(rows)} rows with product images; "
            f"cannot sample {args.sample_size}."
        )

    samples = []
    for sample_index in range(args.sample_count):
        samples.append(
            {
                "category": MARKET_SHARE_CATEGORY,
                "sample_index": sample_index,
                "sample_size": args.sample_size,
                "items": rng.sample(rows, args.sample_size),
            }
        )
    return samples


def normalize_bestseller_labels(skus: list[dict[str, Any]], seed: int) -> None:
    rng = random.Random(seed)
    for sku in skus:
        if sku.get("bestseller_badge") != "none":
            sku["bestseller_badge"] = rng.choice(MARKET_SHARE_BESTSELLER_LABELS)


def promotion_count(skus: list[dict[str, Any]]) -> int:
    return sum(1 for sku in skus if sku.get("promotion") != "none")


def bestseller_count(skus: list[dict[str, Any]]) -> int:
    return sum(1 for sku in skus if sku.get("bestseller_badge") != "none")


def build_market_share_payloads(args: argparse.Namespace) -> list[dict[str, Any]]:
    if not args.original_image.exists() or args.original_image.stat().st_size == 0:
        raise FileNotFoundError(f"Original image is missing or empty: {args.original_image}")
    if args.tag_reference_image and (not args.tag_reference_image.exists() or args.tag_reference_image.stat().st_size == 0):
        raise FileNotFoundError(f"Tag reference image is missing or empty: {args.tag_reference_image}")

    payloads = []
    for index, sample in enumerate(sample_tortilla_products(args), start=1):
        sample_seed = args.seed + index - 1
        edit_seed = args.seed + 1000 + index - 1
        label_seed = args.seed + 2000 + index - 1
        base_payload = build_generate_payload(sample, seed=sample_seed)
        attach_product_images_to_payload(base_payload, args.product_image_dir, allow_missing=False)
        edit_payload = build_edit_payload(args.original_image, base_payload, seed=edit_seed)
        normalize_bestseller_labels(edit_payload["skus"], seed=label_seed)
        edit_payload.update(
            {
                "mode": "edit",
                "category": MARKET_SHARE_CATEGORY,
                "market_share_experiment": True,
                "experiment": "market_share",
                "scenario_id": f"tortilla_chips_market_share_{index:03d}",
                "sample_index": index,
                "prompt_instruction": SHOPPER_INSTRUCTION,
                "shopper_instruction": SHOPPER_INSTRUCTION,
                "experiment_label_fields": ["price", "category_name", "item", "flavor", "size"],
                "input_image": str(args.original_image),
                "force_product_references_in_edit": True,
                "reference_sheet_only": True,
                "style": "realistic 2 by 4 grocery shelf market-share choice stimulus",
                "notes": (
                    "Edit the provided original shelf image into a tortilla chips market-share choice stimulus. "
                    "Keep exactly eight focal products in a strict two-row by four-column shelf grid. "
                    "Use one complete normal physical shelf price tag per product, preserving the full main tag as an "
                    "intact white or light-yellow paper tag with price, category, item, flavor, and size readable. "
                    "Render promotion and bestseller fields as realistic supermarket shelf talkers: separate paper tags "
                    "clipped to the rail in front of, below, or beside the regular white tag, similar to Safeway Club Price "
                    "tags. Do not put promotion or bestseller text inside the main shelf tag, do not replace a tag row with "
                    "a colored band, and do not draw cartoon stickers, starbursts, package badges, or floating icons. "
                    "Do not write the shopper instruction, task title, Choose text, banners, or explanatory text in the image."
                ),
                "randomization": {
                    "item": "sample 8 tortilla chips SKUs with product reference images via shelf_sampling catalog rows",
                    "position": "shuffle positions_2x4() in shelf_sampling.build_edit_payload",
                    "price": "base_price * logNormal(0, 0.3) in shelf_sampling.perturb_edit_attributes",
                    "size": "shelf_sampling.infer_size or existing SKU size",
                    "promotion": "randomly choose 1-4 SKUs and set promotion='Promotion'",
                    "bestseller_badge": "randomly choose 1-4 SKUs and assign BEST SELLER, TOP PICK, or HOT",
                },
                "seeds": {
                    "sample_seed": sample_seed,
                    "edit_seed": edit_seed,
                    "label_seed": label_seed,
                },
            }
        )
        if args.tag_reference_image:
            edit_payload["tag_reference_image"] = str(args.tag_reference_image)
        edit_payload.pop("correct_sku_id", None)
        validate_market_share_payload(edit_payload)
        payloads.append(edit_payload)
    return payloads


def validate_market_share_payload(payload: dict[str, Any]) -> None:
    if "correct_sku_id" in payload:
        raise ValueError(f"{payload['scenario_id']} must not include correct_sku_id.")
    if payload.get("mode") != "edit":
        raise ValueError(f"{payload['scenario_id']} must use edit mode.")
    if Path(payload["input_image"]) != DEFAULT_ORIGINAL_IMAGE and not Path(payload["input_image"]).exists():
        raise FileNotFoundError(f"{payload['scenario_id']} input image not found: {payload['input_image']}")
    skus = payload.get("skus", [])
    if len(skus) != 8:
        raise ValueError(f"{payload['scenario_id']} has {len(skus)} SKUs, expected 8.")
    expected_positions = {json.dumps(position, sort_keys=True) for position in positions_2x4()}
    actual_positions = {json.dumps(sku.get("position"), sort_keys=True) for sku in skus}
    if actual_positions != expected_positions:
        raise ValueError(f"{payload['scenario_id']} has invalid 2x4 positions.")
    promo_n = promotion_count(skus)
    badge_n = bestseller_count(skus)
    if not 1 <= promo_n <= 4:
        raise ValueError(f"{payload['scenario_id']} promotion count must be 1-4, got {promo_n}.")
    if not 1 <= badge_n <= 4:
        raise ValueError(f"{payload['scenario_id']} bestseller count must be 1-4, got {badge_n}.")
    for sku in skus:
        image_path = Path(str(sku.get("product_image", "")))
        if not image_path.exists():
            raise FileNotFoundError(f"{payload['scenario_id']} product image not found: {image_path}")


def write_requests(args: argparse.Namespace, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manifest_items = []
    requests_dir = args.output_root / "requests"
    screens_dir = args.output_root / "screens"
    requests_dir.mkdir(parents=True, exist_ok=True)
    screens_dir.mkdir(parents=True, exist_ok=True)

    for index, payload in enumerate(payloads, start=1):
        scenario_id = payload["scenario_id"]
        request_file = requests_dir / f"{index:03d}_{scenario_id}.json"
        screen_file = screens_dir / f"{index:03d}_{scenario_id}.png"
        request_payload = copy.deepcopy(payload)
        request_file.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest_items.append(
            {
                "dataset": "tortilla_chips",
                "category": MARKET_SHARE_CATEGORY,
                "experiment": "market_share",
                "scenario_id": scenario_id,
                "item_key": f"tortilla_chips/market_share/{index:03d}_{scenario_id}",
                "mode": "edit",
                "input_image": str(args.original_image),
                "tag_reference_image": str(args.tag_reference_image) if args.tag_reference_image else None,
                "prompt_instruction": SHOPPER_INSTRUCTION,
                "shopper_instruction": SHOPPER_INSTRUCTION,
                "promotion_count": promotion_count(payload["skus"]),
                "bestseller_count": bestseller_count(payload["skus"]),
                "randomization": payload["randomization"],
                "seeds": payload["seeds"],
                "request_file": str(request_file),
                "screen_file": str(screen_file),
                "skus": payload["skus"],
            }
        )

    args.output_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "output_root": str(args.output_root),
        "created_at": utc_now(),
        "experiment": "market_share",
        "dataset": "tortilla_chips",
        "category": MARKET_SHARE_CATEGORY,
        "seed": args.seed,
        "sample_count": args.sample_count,
        "sample_size": args.sample_size,
        "original_image": str(args.original_image),
        "catalog_file": str(args.catalog_file),
                "product_image_dir": str(args.product_image_dir),
                "tag_reference_image": str(args.tag_reference_image) if args.tag_reference_image else None,
                "count": len(manifest_items),
        "items": manifest_items,
    }
    (args.output_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_items


def command_for(args: argparse.Namespace, item: dict[str, Any]) -> list[str]:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--request-file",
        item["request_file"],
        "--output-file",
        item["screen_file"],
        "--reference-sheet-only",
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--aspect-ratio",
        args.aspect_ratio,
        "--image-size",
        args.image_size,
    ]
    if args.model:
        cmd.extend(["--model", args.model])
    return cmd


def output_ready(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def run_generation(args: argparse.Namespace, manifest_items: list[dict[str, Any]]) -> None:
    selected = manifest_items[: args.limit] if args.limit else manifest_items
    failures = []
    for index, item in enumerate(selected, start=1):
        output = Path(item["screen_file"])
        if args.skip_existing and output_ready(output):
            print(f"[{index}/{len(selected)}] skip existing {output}", flush=True)
            continue
        cmd = command_for(args, item)
        for attempt in range(1, args.attempts + 1):
            print(f"[{index}/{len(selected)}] edit {item['scenario_id']} attempt {attempt}/{args.attempts}", flush=True)
            try:
                subprocess.run(cmd, check=True, timeout=args.subprocess_timeout_seconds)
                if not output_ready(output):
                    raise RuntimeError(f"Command succeeded but output image is missing or empty: {output}")
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError) as exc:
                if attempt >= args.attempts:
                    failures.append({"scenario_id": item["scenario_id"], "error": str(exc)})
                    print(f"Failed {item['scenario_id']}: {exc}", flush=True)
                    break
                print(f"Retrying in {args.retry_delay_seconds}s after: {exc}", flush=True)
                time.sleep(args.retry_delay_seconds)
    if failures:
        path = args.output_root / "failed_items.json"
        path.write_text(json.dumps({"count": len(failures), "items": failures}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError(f"Finished with {len(failures)} failed items. See {path}")


def main() -> None:
    args = parse_args()
    payloads = build_market_share_payloads(args)
    manifest_items = write_requests(args, payloads)
    print(
        json.dumps(
            {
                "output_root": str(args.output_root),
                "requests": len(manifest_items),
                "manifest": str(args.output_root / "manifest.json"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    if args.generate:
        run_generation(args, manifest_items)


if __name__ == "__main__":
    main()
