from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ASSET_ROOT = Path(__file__).with_name("assets")
DEFAULT_BACKGROUND = ASSET_ROOT / "backgrounds" / "clean_shelf.png"
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("output") / "generated_shelves"

SHELF_POSITIONS = {
    1: 220,
    2: 500,
    3: 780,
}

COL_POSITIONS = {
    1: 150,
    2: 420,
    3: 690,
    4: 960,
    5: 1230,
}

PRODUCT_SIZE = (220, 250)
PRICE_TAG_SIZE = (220, 90)


def pick_font(size: int):
    for candidate in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        trial = " ".join(current + [word])
        if draw.textlength(trial, font=font) <= width or not current:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_color(seed: str) -> str:
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return "#" + digest[:6]


def make_placeholder_packshot(sku: dict[str, Any]) -> Image.Image:
    width, height = PRODUCT_SIZE
    image = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)

    bg = stable_color(sku["sku_id"])
    body_font = pick_font(22)
    small_font = pick_font(16)

    draw.rounded_rectangle((6, 6, width - 6, height - 6), radius=18, fill=bg, outline="#1F2937", width=4)
    draw.rectangle((18, height - 72, width - 18, height - 18), fill="#FFF8E7", outline="#1F2937", width=2)

    title_lines = wrap_text(draw, sku["name"], body_font, width - 34)
    y = 24
    for line in title_lines[:3]:
        draw.text((18, y), line, font=body_font, fill="white")
        y += 28

    draw.text((18, height - 64), sku["brand"], font=small_font, fill="#111827")
    draw.text((18, height - 42), sku["size"], font=small_font, fill="#111827")
    return image


def load_product_packshot(sku: dict[str, Any]) -> Image.Image:
    image_path = sku.get("image_path")
    if image_path:
        path = Path(image_path)
        if path.exists():
            image = Image.open(path).convert("RGBA")
            return image.resize(PRODUCT_SIZE)
    return make_placeholder_packshot(sku)


def build_catalog_map(catalog_items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["sku_id"]: item for item in catalog_items}


def load_price_tag(style: str) -> Image.Image:
    tag_path = ASSET_ROOT / "price_tags" / f"{style}.png"
    if not tag_path.exists():
        raise FileNotFoundError(f"Missing price tag template: {tag_path}")
    return Image.open(tag_path).convert("RGBA")


def validate_grid_position(row: int, col: int) -> None:
    if row not in SHELF_POSITIONS:
        raise ValueError(f"Unsupported row {row}. Allowed rows: {sorted(SHELF_POSITIONS)}")
    if col not in COL_POSITIONS:
        raise ValueError(f"Unsupported col {col}. Allowed cols: {sorted(COL_POSITIONS)}")


def expand_placements(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    if scenario.get("placements"):
        return scenario["placements"]

    placements = []
    sku_ids = scenario.get("sku_ids", [])
    for index, sku_id in enumerate(sku_ids):
        row = index // len(COL_POSITIONS) + 1
        col = index % len(COL_POSITIONS) + 1
        placements.append(
            {
                "sku_id": sku_id,
                "row": row,
                "col": col,
                "price_style": "regular",
            }
        )
    return placements


def paste_product(scene: Image.Image, sku: dict[str, Any], placement: dict[str, Any]) -> None:
    row = placement["row"]
    col = placement["col"]
    validate_grid_position(row, col)
    offset_x = int(placement.get("offset_x", 0))
    offset_y = int(placement.get("offset_y", 0))

    x = COL_POSITIONS[col] + offset_x
    y = SHELF_POSITIONS[row] + offset_y

    packshot = load_product_packshot(sku)
    scene.alpha_composite(packshot, (x, y))

    style = placement.get("price_style")
    if style:
        tag = load_price_tag(style)
        tag_x = x
        tag_y = y + PRODUCT_SIZE[1] + 6
        max_tag_y = scene.height - PRICE_TAG_SIZE[1] - 20
        if tag_y > max_tag_y:
            tag_y = y - PRICE_TAG_SIZE[1] - 10
        scene.alpha_composite(tag, (tag_x, tag_y))


def paste_featured_sign(scene: Image.Image, placement: dict[str, Any]) -> None:
    if not placement.get("featured"):
        return
    sign_path = ASSET_ROOT / "signage" / "featured.png"
    sign = Image.open(sign_path).convert("RGBA")
    row = placement["row"]
    col = placement["col"]
    validate_grid_position(row, col)
    x = COL_POSITIONS[col] - 40 + int(placement.get("offset_x", 0))
    y = SHELF_POSITIONS[row] - 110 + int(placement.get("offset_y", 0))
    scene.alpha_composite(sign, (x, y))


def render_scene(
    catalog_map: dict[str, dict[str, Any]],
    scenario: dict[str, Any],
    output_dir: Path,
    background_path: Path,
) -> Path:
    base = Image.open(background_path).convert("RGBA")
    draw = ImageDraw.Draw(base)

    title = scenario.get("title", scenario["scenario_id"])
    draw.text((100, 176), title, font=pick_font(24), fill="#5B4633")

    placements = expand_placements(scenario)
    for placement in placements:
        sku = catalog_map[placement["sku_id"]]
        paste_product(base, sku, placement)
        paste_featured_sign(base, placement)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f'{scenario["scenario_id"]}.png'
    base.convert("RGB").save(output_path)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a batch of deterministic shelf stimuli.")
    parser.add_argument("--catalog-file", type=Path, required=True, help="Path to the SKU catalog JSON.")
    parser.add_argument("--scenario-file", type=Path, required=True, help="Path to the scenario JSON.")
    parser.add_argument("--background-file", type=Path, default=DEFAULT_BACKGROUND, help="Shelf background asset.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for generated PNGs.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog = load_json(args.catalog_file)
    scenarios = load_json(args.scenario_file)
    catalog_map = build_catalog_map(catalog)

    if not args.background_file.exists():
        raise FileNotFoundError(
            f"Background not found: {args.background_file}. Run generate_asset_library.py first."
        )

    written_files = []
    for scenario in scenarios:
        written_files.append(render_scene(catalog_map, scenario, args.output_dir, args.background_file))

    for path in written_files:
        print(path)


if __name__ == "__main__":
    main()
