from __future__ import annotations

import argparse
import base64
import json
import os
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from shelf_sampling import (
    BESTSELLER_BADGE_LABELS,
    DEFAULT_CATALOG_FILE,
    INVENTORY_REMAINING_LEVELS,
    available_categories,
    build_edit_payload,
    build_generate_payload,
    load_catalog,
    parse_categories,
    sample_products,
)


API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-5.4-image-2"
DEFAULT_PRODUCT_IMAGE_DIR = Path(__file__).resolve().parents[1] / "pic" / "images"
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
IMAGE_SUFFIX_PRIORITY = {".png": 0, ".jpg": 1, ".jpeg": 2, ".webp": 3, ".gif": 4}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pure-LLM shelf image generation and editing via OpenRouter Image 2."
    )
    parser.add_argument("--request-file", type=Path, help="JSON file describing one shelf request.")
    parser.add_argument("--output-file", type=Path, help="Output PNG path for a single request.")
    parser.add_argument("--output-dir", type=Path, help="Output directory for sampled multi-request runs.")
    parser.add_argument("--mode", choices=["generate", "edit"], help="Build requests from catalog sampling.")
    parser.add_argument("--catalog-file", type=Path, default=DEFAULT_CATALOG_FILE, help="Catalog CSV for sampling.")
    parser.add_argument("--category", "--categories", dest="categories", action="append", help="Category name. Repeat or comma-separate. Defaults to all categories.")
    parser.add_argument("--sample-size", type=int, default=8, help="Number of products per sampled category.")
    parser.add_argument("--sample-count", type=int, default=1, help="Number of samples per category.")
    parser.add_argument("--seed", type=int, help="Random seed for sampling and perturbations.")
    parser.add_argument("--input-image", type=Path, help="Original shelf image for edit mode.")
    parser.add_argument("--base-request-file", type=Path, help="Generate request JSON to preserve SKU identities in edit mode.")
    parser.add_argument("--product-image-dir", type=Path, default=DEFAULT_PRODUCT_IMAGE_DIR, help="Directory containing product reference images.")
    parser.add_argument("--reference-sheet-only", action="store_true", help="Send only the PIL 2x4 product reference sheet, not the eight individual product images.")
    parser.add_argument("--allow-missing-product-images", action="store_true", help="Allow text-only fallback when some SKU images are missing.")
    parser.add_argument("--bestseller-count", type=int, choices=[1, 2, 3, 4], help="Number of products to receive a bestseller badge in sampled edit mode.")
    parser.add_argument("--request-output-file", type=Path, help="Optional JSON file to save built request payloads.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter image model.")
    parser.add_argument("--aspect-ratio", default="4:3", help="Image aspect ratio.")
    parser.add_argument("--image-size", default="1K", choices=["1K", "2K"], help="Image size.")
    parser.add_argument("--timeout-seconds", type=int, default=360, help="HTTP timeout in seconds.")
    return parser.parse_args()


def load_request(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def encode_local_image(path: Path) -> str:
    from io import BytesIO

    from PIL import Image

    with Image.open(path) as image:
        frame = image.convert("RGBA")
        buffer = BytesIO()
        frame.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def image_digits(path: Path) -> str:
    return "".join(re.findall(r"\d+", path.stem.split("_")[-1]))


def image_rank(path: Path) -> int | None:
    match = re.search(r"rank(\d+)", path.stem, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def list_product_images(product_image_dir: Path) -> list[Path]:
    if not product_image_dir.exists():
        return []
    images = [p for p in product_image_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES]
    return sorted(images, key=lambda p: (image_rank(p) or 9999, IMAGE_SUFFIX_PRIORITY.get(p.suffix.lower(), 99), p.name))


def find_product_image(item: dict[str, Any], product_images: list[Path]) -> Path | None:
    sku_id = str(item.get("sku_id") or item.get("upc_id") or "").split(".", 1)[0].lstrip("0")
    if sku_id:
        for path in product_images:
            digits = image_digits(path).lstrip("0")
            if digits.startswith(sku_id):
                return path.resolve()
    return None


def attach_product_images_to_payload(
    payload: dict[str, Any],
    product_image_dir: Path,
    allow_missing: bool,
) -> dict[str, Any]:
    product_images = list_product_images(product_image_dir)
    if not product_images:
        if allow_missing:
            return payload
        raise FileNotFoundError(f"No product reference images found in {product_image_dir}")

    missing = []
    for sku in payload["skus"]:
        image_path = find_product_image(sku, product_images)
        if image_path:
            sku["product_image"] = str(image_path)
        else:
            sku.pop("product_image", None)
            missing.append(f'{sku["sku_id"]} ({sku["item"]})')

    if missing and not allow_missing:
        raise FileNotFoundError(
            "Missing product reference images for these SKUs; refusing to generate from text-only cues:\n"
            + "\n".join(f"- {item}" for item in missing)
        )
    return payload


def has_product_image(row: dict[str, Any], product_images: list[Path]) -> bool:
    sku_like = {
        "sku_id": row.get("upc_id"),
        "upc_id": row.get("upc_id"),
        "item": row.get("upc_description"),
        "source_row": row,
    }
    return find_product_image(sku_like, product_images) is not None


def sample_products_with_product_images(
    categories: list[str] | None,
    sample_size: int,
    sample_count: int,
    catalog_file: Path,
    product_image_dir: Path,
    seed: int | None,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    catalog = load_catalog(catalog_file)
    product_images = list_product_images(product_image_dir)
    if not product_images:
        raise FileNotFoundError(f"No product reference images found in {product_image_dir}")

    requested = categories or available_categories(catalog)
    samples: list[dict[str, Any]] = []
    skipped_categories = []
    for category in requested:
        rows = [row for row in catalog if str(row["category_name"]) == category]
        if not rows:
            raise ValueError(f"Category not found in catalog: {category}")
        rows_with_images = [row for row in rows if has_product_image(row, product_images)]
        if len(rows_with_images) < sample_size:
            if categories:
                raise ValueError(
                    f"Category {category} has only {len(rows_with_images)} rows with product images; "
                    f"cannot sample {sample_size}."
                )
            skipped_categories.append(category)
            continue
        for sample_index in range(sample_count):
            samples.append(
                {
                    "category": category,
                    "sample_index": sample_index,
                    "sample_size": sample_size,
                    "items": rng.sample(rows_with_images, sample_size),
                }
            )
    if not samples:
        skipped = ", ".join(skipped_categories) if skipped_categories else "none"
        raise ValueError(f"No categories have enough product images for sample_size={sample_size}. Skipped: {skipped}")
    return samples


def format_sku_lines(items: list[dict[str, Any]]) -> str:
    lines = []
    for index, item in enumerate(items, start=1):
        promo = item.get("promotion", "none")
        bestseller_badge = item.get("bestseller_badge", item.get("bestseller", "none"))
        inventory_remaining = item.get("inventory_remaining", "unknown")
        price = item.get("price", "unknown")
        size = item.get("size", "unknown")
        brand = item.get("brand")
        color = item.get("color")
        rating = item.get("rating")
        reviews = item.get("number_of_reviews", item.get("reviews"))
        product_number = item.get("product_number", index)
        source = item.get("source_row", {})
        rank = source.get("rank_within_category", "unknown") if isinstance(source, dict) else "unknown"
        image_note = f", product_reference_image={index}" if item.get("product_image") else ", product_reference_image=missing"
        optional_fields = []
        if brand not in (None, ""):
            optional_fields.append(f'brand="{brand}"')
        if color not in (None, ""):
            optional_fields.append(f'color="{color}"')
        if rating not in (None, ""):
            optional_fields.append(f'rating="{rating}"')
        if reviews not in (None, ""):
            optional_fields.append(f'number_of_reviews="{reviews}"')
        optional_text = ", " + ", ".join(optional_fields) if optional_fields else ""
        lines.append(
            f'- product_number={product_number}, sku_id={item["sku_id"]}: item="{item["item"]}", size="{size}", price="{price}"{optional_text}, '
            f'promotion="{promo}", bestseller_badge="{bestseller_badge}", inventory_remaining="{inventory_remaining}", '
            f'category="{item.get("category_name", "unknown")}", source_rank="{rank}", '
            f'position=(row {item["position"]["row"]}, col {item["position"]["col"]}){image_note}'
        )
    return "\n".join(lines)


def format_product_reference_lines(items: list[dict[str, Any]]) -> str:
    lines = []
    for index, item in enumerate(items, start=1):
        if not item.get("product_image"):
            continue
        lines.append(
            f'- Product reference image {index} is the exact package for SKU {item["sku_id"]}, '
            f'item="{item["item"]}", position=(row {item["position"]["row"]}, col {item["position"]["col"]}).'
        )
    return "\n".join(lines)


def package_size_scale(size: Any) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)", str(size or ""))
    if not match:
        return 1.0
    amount = float(match.group(1))
    if "ct" in str(size).lower() or "count" in str(size).lower():
        baseline = 18.0
    elif "l" in str(size).lower() and "fl" not in str(size).lower():
        baseline = 1.0
    else:
        baseline = 10.0
    return max(0.72, min(1.18, (amount / baseline) ** 0.25))


def product_realism_instructions(payload: dict[str, Any]) -> str:
    if payload.get("synthetic_products"):
        return (
            "These are synthetic experiment products. Render simple, believable, non-branded retail packages from the "
            "structured product titles and attributes. Do not add real logos unless the brand is explicitly listed in the "
            "structured configuration. "
        )
    return (
        "All listed SKUs are real retail products. When product reference images are provided, use those images as the "
        "primary source of truth for package identity, brand, colors, logos, shape, and front-panel artwork. Do not invent, "
        "replace, redraw from memory, or hallucinate different packaging. Some item names are abbreviated POS descriptions; "
        "use the reference images to resolve the true original product packaging rather than generic placeholder packaging. "
        "A 2x4 product reference sheet is provided; treat that sheet as the layout and relative package-size guide. "
        "If individual product images are also provided, use them for high-detail package details. "
        "Copy the visible package silhouette, aspect ratio, color blocking, and front-facing "
        "artwork from the references as closely as the image model allows. "
        "The visible package format and apparent package size must match the provided size field: for example, small bags, "
        "family-size bags, boxes, bottles, cans, jars, tubs, pints, and multi-packs should look physically consistent with "
        "their stated ounces, fluid ounces, liters, counts, or quarts. "
    )


def reference_input_instructions(payload: dict[str, Any]) -> str:
    if not any(item.get("product_image") for item in payload.get("skus", [])):
        return (
            "No product reference images are provided for this request. Generate clear generic package visuals from the "
            "structured fields, and make the experiment labels the most legible part of each product cell. "
        )
    if payload.get("reference_sheet_only"):
        return (
            "Use the provided 2x4 product reference sheet as the only visual source for the eight focal products. "
            "Do not expect separate individual product images; each cell in the reference sheet corresponds to the row and column in the requested shelf. "
            "Copy package identity, colors, silhouette, front-panel artwork, and relative package size from that sheet. "
        )
    return (
        "Use the provided 2x4 product reference sheet as the layout and relative-size guide, and use the eight individual "
        "product reference images as high-detail package references. "
    )


def bestseller_badge_instructions() -> str:
    labels = ", ".join(BESTSELLER_BADGE_LABELS)
    return (
        "The bestseller_badge field is a separate merchandising badge, not a price promotion. "
        f"When bestseller_badge is not 'none', render a clear small hot-selling badge near that SKU using exactly one of these texts: {labels}. "
        "Keep bestseller badges visually distinct from shelf price labels and promotion markers. "
    )


def inventory_visual_instructions(payload: dict[str, Any]) -> str:
    strategy = payload.get("inventory_visual_strategy", "front_facings")
    levels = ", ".join(str(level) for level in INVENTORY_REMAINING_LEVELS)
    base = (
        "Inventory is a visual experimental variable. Use the inventory_remaining field to control how many physical units "
        "or facings of that same SKU appear in its shelf cell. Do not render text labels, stock numbers, inventory signs, "
        "or digital counters for inventory. Show inventory only through visible product quantity, shelf fullness, empty gaps, "
        "and how far products extend backward on the shelf. "
        f"The intended inventory scale is {levels}: 1-2 means very low stock with obvious empty space; 3-4 means low stock; "
        "6-8 means medium stock; 10-12 means high stock, dense and nearly full. "
    )
    strategies = {
        "front_facings": (
            "Prompt strategy: front-facing facings. Encode inventory mainly by the number of front-facing copies in each cell. "
            "Low inventory should show only one or two visible front packages and large empty shelf gaps; high inventory should show many repeated front facings filling the cell. "
        ),
        "horizontal_facings": (
            "Prompt strategy: horizontal shelf width. Encode inventory by how much horizontal width the SKU occupies in its cell. "
            "Low inventory should occupy a narrow slice with visible blank shelf space; high inventory should span almost the full cell with repeated packages side by side. "
        ),
        "depth_rows": (
            "Prompt strategy: depth rows. Encode inventory by rows of the same product receding backward into the shelf. "
            "Low inventory should have only front items with empty space behind them; high inventory should show several rows deep, with product copies visible behind the front row. "
        ),
        "stacked_depth": (
            "Prompt strategy: stacked and deep stock. Encode inventory by a combination of vertical stacking and depth. "
            "Low inventory should show a small loose stack or one package; high inventory should show stacked layers and deeper rows while keeping each SKU inside its 2x4 cell. "
        ),
        "empty_gap": (
            "Prompt strategy: empty-gap emphasis. Encode inventory through negative space: low inventory cells have large clean empty slots, exposed shelf surface, and visible back panel; "
            "high inventory cells are visually full with only tiny gaps. "
        ),
    }
    return base + strategies.get(strategy, strategies["front_facings"])


def experiment_label_instructions(payload: dict[str, Any]) -> str:
    fields = payload.get("experiment_label_fields")
    if not fields:
        return ""
    joined = ", ".join(str(field) for field in fields)
    return (
        f"This is a controlled product-choice experiment. In every one of the eight target cells, render large, crisp, "
        f"front-facing labels for these fields exactly from the structured configuration: {joined}. "
        "The product number must be visually prominent. Prices, ratings, review counts, brands, and colors are decision-critical "
        "experimental variables, so they must be readable and must not be omitted, distorted, rounded, or replaced with other values. "
    )


def build_generate_prompt(payload: dict[str, Any]) -> str:
    style = payload.get("style", "clean grocery shelf experiment image")
    category = payload.get("category", "grocery")
    notes = payload.get(
        "notes",
        "The shelf should be front-facing, visually clean, and easy to read. Distinguish products clearly.",
    )
    return (
        f"Generate one {style} for category {category}. "
        f"{notes} Respect the following structured shelf configuration exactly as much as possible.\n"
        f"{format_sku_lines(payload['skus'])}\n"
        "Product reference mapping:\n"
        f"{format_product_reference_lines(payload['skus'])}\n"
        f"{product_realism_instructions(payload)}"
        f"{reference_input_instructions(payload)}"
        f"{bestseller_badge_instructions()}"
        f"{inventory_visual_instructions(payload)}"
        f"{experiment_label_instructions(payload)}"
        "Use ONLY the provided product references for the eight focal products when product references are provided. "
        "Do not redesign packages, substitute flavors, simplify logos, or change package colors. "
        "You may adjust perspective, lighting, shadows, and shelf integration so the final scene is realistic, "
        "but preserve the product package appearance and relative package sizes from the reference sheet and individual images. "
        "Use a strict 2 by 4 layout: two horizontal shelf rows and four product columns, for exactly eight focal products. "
        "Render a realistic grocery shelf photograph that matches a real supermarket shelf. "
        "The shelf should be densely stocked and visually full, with products filling almost all visible facing space. "
        "Avoid large empty gaps or obviously sparse experimental layouts unless a gap is explicitly requested. "
        "Use repeated facings of the requested target SKU when inventory_remaining is high; use visible empty shelf space when inventory_remaining is low. "
        "Use neighboring filler products only outside the eight target cells when needed so the shelf looks naturally merchandised. "
        "Keep the requested target SKUs at their specified positions and preserve their item identity, price cue, promotion type, bestseller badge, and experiment labels. "
        "Make price labels, promotion markers, bestseller badges, and experiment labels visible and believable. "
        "The final image should look like a real fully merchandised supermarket shelf rather than a minimal mockup."
    )


def build_edit_prompt(payload: dict[str, Any]) -> str:
    notes = payload.get(
        "notes",
        "Edit the provided shelf image while preserving the overall shelf framing and realism as much as possible.",
    )
    return (
        f"Edit the provided grocery shelf image. {notes} "
        "Update it to reflect the following structured shelf configuration exactly as much as possible.\n"
        f"{format_sku_lines(payload['skus'])}\n"
        "Product reference mapping:\n"
        f"{format_product_reference_lines(payload['skus'])}\n"
        f"{product_realism_instructions(payload)}"
        f"{reference_input_instructions(payload)}"
        f"{bestseller_badge_instructions()}"
        f"{inventory_visual_instructions(payload)}"
        f"{experiment_label_instructions(payload)}"
        "Use the product references as the exact package sources for the eight focal products. "
        "Do not change product identities, shelf framing, background, lighting, camera angle, or visual style. "
        "Only change the requested attributes represented in the structured configuration: product positions, promotion labels, bestseller badges, inventory quantities, prices, and sizes. "
        "Do not change package designs, product identities, or any unrequested visual attributes. "
        "Keep it as a coherent shelf photograph and change only what is needed to match those instructions."
    )


def build_sampled_payloads(args: argparse.Namespace) -> list[dict[str, Any]]:
    if not args.mode:
        raise ValueError("Use --request-file or provide --mode generate/edit for catalog sampling.")
    if args.mode == "edit" and args.base_request_file:
        if not args.input_image:
            raise ValueError("--input-image is required for sampled edit mode.")
        base_payload = load_request(args.base_request_file)
        base_payloads = base_payload if isinstance(base_payload, list) else [base_payload]
        return [
            build_edit_payload(args.input_image, payload, seed=args.seed, bestseller_count=args.bestseller_count)
            for payload in base_payloads
        ]
    categories = parse_categories(args.categories)
    if args.product_image_dir and args.product_image_dir.exists() and not args.allow_missing_product_images:
        samples = sample_products_with_product_images(
            categories=categories,
            sample_size=args.sample_size,
            sample_count=args.sample_count,
            catalog_file=args.catalog_file,
            product_image_dir=args.product_image_dir,
            seed=args.seed,
        )
    else:
        samples = sample_products(
            categories=categories,
            sample_size=args.sample_size,
            sample_count=args.sample_count,
            catalog_file=args.catalog_file,
            seed=args.seed,
        )
    payloads = [build_generate_payload(sample, seed=args.seed) for sample in samples]
    if args.mode == "generate":
        return payloads
    if not args.input_image:
        raise ValueError("--input-image is required for sampled edit mode.")
    return [
        build_edit_payload(args.input_image, payload, seed=args.seed, bestseller_count=args.bestseller_count)
        for payload in payloads
    ]


def resolve_output_file(args: argparse.Namespace, payload: dict[str, Any], index: int, total: int) -> Path:
    if args.output_file and total == 1:
        return args.output_file
    output_dir = args.output_dir or (args.output_file.parent if args.output_file else Path("output"))
    category = str(payload.get("category", "shelf")).lower().replace(" ", "_").replace("/", "_")
    mode = {"generate": "生图", "edit": "改图"}.get(payload["mode"], payload["mode"])
    sample_index = payload.get("sample_index", index)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_dir / f"{timestamp}_{mode}_{category}_sample_{sample_index}.png"


def save_request_payloads(path: Path, payloads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content: Any = payloads[0] if len(payloads) == 1 else payloads
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


def product_reference_thumbnail_path(output_file: Path) -> Path:
    return output_file.with_name(f"{output_file.stem}_商品参考.png")


def render_product_reference_thumbnail(
    payload: dict[str, Any],
    output_file: Path,
    cell_size: tuple[int, int] = (240, 240),
    label_height: int = 76,
) -> Path | None:
    items = [item for item in payload.get("skus", []) if item.get("product_image")]
    if not items:
        return None

    from PIL import Image, ImageDraw, ImageOps

    rows = int(payload.get("layout", {}).get("rows", 2))
    cols = int(payload.get("layout", {}).get("cols", 4))
    cell_w, cell_h = cell_size
    margin = 18
    gap = 14
    title_h = 38
    canvas_w = cols * cell_w + (cols - 1) * gap + 2 * margin
    canvas_h = rows * (cell_h + label_height) + (rows - 1) * gap + 2 * margin + title_h
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)
    title = f'{payload.get("mode", "request")} | {payload.get("category", "category")} | product references'
    draw.text((margin, margin), title, fill=(20, 20, 20))

    for item in items:
        position = item.get("position", {})
        row = int(position.get("row", 1))
        col = int(position.get("col", 1))
        x = margin + (col - 1) * (cell_w + gap)
        y = margin + title_h + (row - 1) * (cell_h + label_height + gap)
        draw.rectangle((x, y, x + cell_w - 1, y + cell_h + label_height - 1), outline=(210, 210, 210), width=1)

        image_path = Path(item["product_image"])
        with Image.open(image_path) as image:
            scale = package_size_scale(item.get("size"))
            max_w = int((cell_w - 20) * scale)
            max_h = int((cell_h - 20) * scale)
            product = ImageOps.contain(image.convert("RGBA"), (max_w, max_h))
        bg = Image.new("RGBA", (cell_w - 20, cell_h - 20), (255, 255, 255, 255))
        px = x + 10 + ((cell_w - 20) - product.width) // 2
        py = y + 10 + ((cell_h - 20) - product.height) // 2
        canvas.paste(bg.convert("RGB"), (x + 10, y + 10))
        canvas.paste(product.convert("RGB"), (px, py), product)

        promo = item.get("promotion", "none")
        bestseller_badge = item.get("bestseller_badge", item.get("bestseller", "none"))
        label_lines = [
            f'#{item.get("product_number", "?")} {item["sku_id"]} | {item.get("price", "unknown")}',
            f'{item.get("brand", "")} {item.get("color", "")}'.strip(),
            f'rating: {item.get("rating", "")} reviews: {item.get("number_of_reviews", item.get("reviews", ""))}'.strip(),
            f'size: {item.get("size", "unknown")} inv: {item.get("inventory_remaining", "unknown")}',
            promo if promo != "none" else "",
            f"badge: {bestseller_badge}" if bestseller_badge != "none" else "",
        ]
        label_y = y + cell_h + 6
        for line in label_lines:
            if line:
                draw.text((x + 8, label_y), line[:38], fill=(30, 30, 30))
            label_y += 18

    thumbnail_file = product_reference_thumbnail_path(output_file)
    thumbnail_file.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(thumbnail_file)
    return thumbnail_file


def product_image_content_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    parts = []
    for item in payload["skus"]:
        image_path = item.get("product_image")
        if not image_path:
            continue
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Product reference image not found for SKU {item['sku_id']}: {path}")
        parts.append({"type": "image_url", "image_url": {"url": encode_local_image(path)}})
    return parts


def product_reference_sheet_content_part(payload: dict[str, Any]) -> dict[str, Any] | None:
    sheet_path = payload.get("product_reference_sheet")
    if not sheet_path:
        return None
    path = Path(sheet_path)
    if not path.exists():
        raise FileNotFoundError(f"Product reference sheet not found: {path}")
    return {"type": "image_url", "image_url": {"url": encode_local_image(path)}}


def build_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    mode = payload["mode"]
    if mode == "generate":
        content: list[dict[str, Any]] = [{"type": "text", "text": build_generate_prompt(payload)}]
        sheet_part = product_reference_sheet_content_part(payload)
        if sheet_part:
            content.append(sheet_part)
        if not payload.get("reference_sheet_only"):
            content.extend(product_image_content_parts(payload))
        return [{"role": "user", "content": content}]

    if mode == "edit":
        input_image_path = Path(payload["input_image"])
        if not input_image_path.exists():
            raise FileNotFoundError(f"Input image not found for edit mode: {input_image_path}")
        content = [
            {"type": "text", "text": build_edit_prompt(payload)},
            {"type": "image_url", "image_url": {"url": encode_local_image(input_image_path)}},
        ]
        sheet_part = product_reference_sheet_content_part(payload)
        if sheet_part:
            content.append(sheet_part)
        if not payload.get("reference_sheet_only"):
            content.extend(product_image_content_parts(payload))
        return [
            {
                "role": "user",
                "content": content,
            }
        ]

    raise ValueError(f"Unsupported mode: {mode}")


def call_openrouter(
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    aspect_ratio: str,
    image_size: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    response = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://local.codex.workflow",
            "X-OpenRouter-Title": "Shelf Image LLM Workflow",
        },
        json={
            "model": model,
            "messages": messages,
            "modalities": ["image", "text"],
            "image_config": {
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
            },
            "stream": False,
        },
        timeout=timeout_seconds,
    )
    if not response.ok:
        raise RuntimeError(f"OpenRouter image request failed with status {response.status_code}: {response.text}")
    return response.json()


def extract_image_bytes(result: dict[str, Any]) -> bytes:
    message = result["choices"][0]["message"]
    images = message.get("images") or []
    if not images:
        content = message.get("content", "")
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        raise ValueError(f"No generated image found in OpenRouter response. Message content: {content[:1000]}")
    image_url = images[0]["image_url"]["url"]
    if not image_url.startswith("data:image"):
        raise ValueError("Expected a base64 image data URL in the response.")
    return base64.b64decode(image_url.split(",", 1)[1])


def main() -> None:
    args = parse_args()
    if args.request_file:
        payloads = [load_request(args.request_file)]
    else:
        payloads = build_sampled_payloads(args)

    if args.product_image_dir:
        payloads = [
            attach_product_images_to_payload(
                payload=payload,
                product_image_dir=args.product_image_dir,
                allow_missing=args.allow_missing_product_images,
            )
            for payload in payloads
        ]

    for payload in payloads:
        payload["reference_sheet_only"] = args.reference_sheet_only

    if not args.output_file and not args.output_dir:
        raise ValueError("--output-file or --output-dir is required.")

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")

    output_files = [resolve_output_file(args, payload, index, len(payloads)) for index, payload in enumerate(payloads)]

    outputs = []
    reference_thumbnails = []
    for payload, output_file in zip(payloads, output_files, strict=True):
        thumbnail_file = render_product_reference_thumbnail(payload, output_file)
        if thumbnail_file:
            payload["product_reference_sheet"] = str(thumbnail_file)
            reference_thumbnails.append(str(thumbnail_file))

    if args.request_output_file:
        save_request_payloads(args.request_output_file, payloads)

    for payload, output_file in zip(payloads, output_files, strict=True):
        messages = build_messages(payload)
        result = call_openrouter(
            api_key=api_key,
            model=args.model,
            messages=messages,
            aspect_ratio=args.aspect_ratio,
            image_size=args.image_size,
            timeout_seconds=args.timeout_seconds,
        )
        image_bytes = extract_image_bytes(result)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(image_bytes)
        outputs.append(str(output_file))

    print(
        json.dumps(
            {
                "model": args.model,
                "outputs": outputs,
                "reference_thumbnails": reference_thumbnails,
                "request_file": str(args.request_file) if args.request_file else None,
                "request_output_file": str(args.request_output_file) if args.request_output_file else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
