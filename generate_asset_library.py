from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ASSET_ROOT = Path(__file__).with_name("assets")
BACKGROUND_DIR = ASSET_ROOT / "backgrounds"
PRICE_TAG_DIR = ASSET_ROOT / "price_tags"
SIGNAGE_DIR = ASSET_ROOT / "signage"


def pick_font(size: int):
    for candidate in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def make_background(output_path: Path) -> None:
    image = Image.new("RGB", (1600, 1100), "#F2EBDD")
    draw = ImageDraw.Draw(image)

    draw.rectangle((40, 40, 1560, 1060), outline="#8E7458", width=8)
    draw.rounded_rectangle((70, 70, 1530, 160), radius=22, fill="#E8D9C2", outline="#8E7458", width=3)
    draw.text((105, 100), "Shelf Stimulus Background", font=pick_font(40), fill="#4A392B")

    shelf_specs = [
        (240, 268),
        (520, 548),
        (800, 828),
    ]
    for y0, y1 in shelf_specs:
        draw.rectangle((110, y0, 1490, y1), fill="#A67C52")
        draw.rectangle((110, y0 - 10, 1490, y0), fill="#D8C3A5")

    draw.rectangle((90, 190, 110, 870), fill="#9B7B5A")
    draw.rectangle((1490, 190, 1510, 870), fill="#9B7B5A")
    image.save(output_path)


def make_price_tag(style: str, output_path: Path) -> None:
    image = Image.new("RGBA", (220, 90), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    title_font = pick_font(18)
    price_font = pick_font(32)

    if style == "regular":
        fill = "#FFF8E8"
        accent = "#5E503F"
        title = "EVERYDAY"
        old_price = None
    elif style == "sale":
        fill = "#FFE7E2"
        accent = "#C0392B"
        title = "SALE"
        old_price = None
    else:
        fill = "#F3F4F6"
        accent = "#374151"
        title = "MARKDOWN"
        old_price = "$5.99"

    draw.rounded_rectangle((2, 2, 218, 88), radius=16, fill=fill, outline=accent, width=3)
    draw.text((18, 13), title, font=title_font, fill=accent)
    draw.text((24, 38), "$4.79", font=price_font, fill=accent)
    if old_price:
        draw.text((132, 44), old_price, font=title_font, fill="#6B7280")
        draw.line((132, 54, 184, 54), fill="#B91C1C", width=3)
    image.save(output_path)


def make_signage(output_path: Path) -> None:
    image = Image.new("RGBA", (300, 120), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 4, 296, 116), radius=18, fill="#FDE68A", outline="#92400E", width=4)
    draw.text((40, 42), "FEATURED", font=pick_font(34), fill="#78350F")
    image.save(output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the reusable asset library for Part B shelf stimuli.")
    parser.add_argument("--asset-root", type=Path, default=ASSET_ROOT, help="Asset library root directory.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    background_dir = args.asset_root / "backgrounds"
    price_tag_dir = args.asset_root / "price_tags"
    signage_dir = args.asset_root / "signage"
    background_dir.mkdir(parents=True, exist_ok=True)
    price_tag_dir.mkdir(parents=True, exist_ok=True)
    signage_dir.mkdir(parents=True, exist_ok=True)

    make_background(background_dir / "clean_shelf.png")
    make_price_tag("regular", price_tag_dir / "regular.png")
    make_price_tag("sale", price_tag_dir / "sale.png")
    make_price_tag("markdown", price_tag_dir / "markdown.png")
    make_signage(signage_dir / "featured.png")

    print(args.asset_root)


if __name__ == "__main__":
    main()
