from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path
from typing import Any


DEFAULT_CATALOG_FILE = Path(__file__).resolve().parents[1] / "data_clean" / "top_50_skus_selected_categories.csv"
GRID_ROWS = 2
GRID_COLS = 4


def load_catalog(catalog_file: Path = DEFAULT_CATALOG_FILE) -> list[dict[str, Any]]:
    with catalog_file.open("r", encoding="utf-8-sig", newline="") as f:
        return [normalize_row(row) for row in csv.DictReader(f)]


def normalize_row(row: dict[str, str]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        if value is None:
            normalized[key] = value
            continue
        value = value.strip()
        if value == "":
            normalized[key] = value
            continue
        try:
            normalized[key] = float(value) if "." in value else int(value)
        except ValueError:
            normalized[key] = value
    return normalized


def available_categories(catalog: list[dict[str, Any]]) -> list[str]:
    return sorted({str(row["category_name"]) for row in catalog})


def sample_products(
    categories: list[str] | None = None,
    sample_size: int = 8,
    sample_count: int = 1,
    catalog_file: Path = DEFAULT_CATALOG_FILE,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Return sampled rows with all original catalog fields preserved."""
    rng = random.Random(seed)
    catalog = load_catalog(catalog_file)
    requested = categories or available_categories(catalog)
    samples: list[dict[str, Any]] = []

    for category in requested:
        rows = [row for row in catalog if str(row["category_name"]) == category]
        if not rows:
            raise ValueError(f"Category not found in catalog: {category}")
        if len(rows) < sample_size:
            raise ValueError(f"Category {category} has only {len(rows)} rows; cannot sample {sample_size}.")
        for sample_index in range(sample_count):
            selected = rng.sample(rows, sample_size)
            samples.append(
                {
                    "category": category,
                    "sample_index": sample_index,
                    "sample_size": sample_size,
                    "items": selected,
                }
            )
    return samples


def infer_base_price(row: dict[str, Any]) -> float:
    item_qty = as_float(row.get("item_qty"))
    gross_amt = as_float(row.get("gross_amt"))
    net_amt = as_float(row.get("net_amt"))
    if item_qty and item_qty > 0:
        amount = gross_amt if gross_amt and gross_amt > 0 else net_amt
        if amount and amount > 0:
            return max(0.49, amount / item_qty)
    return 3.99


def as_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed):
        return None
    return parsed


def infer_size(row: dict[str, Any], rng: random.Random) -> str:
    category = str(row.get("category_name", "")).lower()
    if "chips" in category:
        return rng.choice(["7 oz", "8.5 oz", "9.25 oz", "10 oz", "13 oz"])
    if "soft drink" in category or "carbonated" in category or "soda" in category:
        return rng.choice(["12 fl oz can", "16.9 fl oz bottle", "20 fl oz bottle", "2 L bottle"])
    if "coffee" in category:
        return rng.choice(["10 oz bag", "12 oz bag", "16 oz bag", "18 ct pods", "24 ct pods"])
    if "cereal" in category:
        return rng.choice(["10.7 oz box", "12 oz box", "14.8 oz box", "18 oz box"])
    if "ice cream" in category:
        return rng.choice(["14 fl oz pint", "1.5 qt tub", "48 fl oz tub"])
    if "yogurt" in category:
        return rng.choice(["5.3 oz cup", "6 oz cup", "24 oz tub", "32 oz tub"])
    if "cracker" in category:
        return rng.choice(["7 oz box", "8.8 oz box", "12 oz box", "13.7 oz box"])
    if "dip" in category or "salsa" in category:
        return rng.choice(["10 oz jar", "12 oz tub", "15.5 oz jar", "16 oz jar"])
    return rng.choice(["8 oz", "12 oz", "16 oz"])


def format_price(price: float) -> str:
    return f"${price:.2f}"


def positions_2x4() -> list[dict[str, int]]:
    return [{"row": row, "col": col} for row in range(1, GRID_ROWS + 1) for col in range(1, GRID_COLS + 1)]


def product_to_sku(row: dict[str, Any], position: dict[str, int], rng: random.Random) -> dict[str, Any]:
    base_price = infer_base_price(row)
    return {
        "sku_id": str(row["upc_id"]),
        "item": str(row["upc_description"]).strip(),
        "category_id": row.get("category_id"),
        "category_name": row.get("category_name"),
        "base_price": format_price(base_price),
        "price": format_price(base_price),
        "promotion": "none",
        "size": infer_size(row, rng),
        "position": position,
        "source_row": row,
    }


def build_generate_payload(sample: dict[str, Any], seed: int | None = None) -> dict[str, Any]:
    rng = random.Random(seed)
    skus = [
        product_to_sku(row, position, rng)
        for row, position in zip(sample["items"], positions_2x4(), strict=True)
    ]
    return {
        "mode": "generate",
        "category": sample["category"],
        "layout": {"rows": GRID_ROWS, "cols": GRID_COLS},
        "sample_index": sample["sample_index"],
        "style": "realistic 2 by 4 grocery shelf experiment image",
        "notes": (
            "Create exactly eight focal products arranged in a two-row by four-column shelf grid. "
            "Each grid cell should show one clearly distinguishable target product with a shelf price label."
        ),
        "skus": skus,
    }


def perturb_edit_attributes(
    skus: list[dict[str, Any]],
    seed: int | None = None,
    promotion_count: int | None = None,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    edited = [dict(item) for item in skus]

    shuffled_positions = positions_2x4()
    rng.shuffle(shuffled_positions)
    for item, position in zip(edited, shuffled_positions, strict=True):
        item["position"] = position
        item.pop("tags", None)
        base_price = as_float(str(item.get("base_price", item.get("price", "3.99"))).replace("$", "")) or 3.99
        item["price"] = format_price(base_price * rng.lognormvariate(0, 0.3))
        item["size"] = item.get("size") or infer_size(item.get("source_row", {}), rng)
        item["promotion"] = "none"

    promotion_n = promotion_count if promotion_count is not None else rng.randint(1, 4)
    promotion_indices = set(rng.sample(range(len(edited)), promotion_n))
    for index in promotion_indices:
        edited[index]["promotion"] = "Promotion"
    return edited


def build_edit_payload(
    input_image: Path,
    base_payload: dict[str, Any],
    seed: int | None = None,
    promotion_count: int | None = None,
) -> dict[str, Any]:
    return {
        **base_payload,
        "mode": "edit",
        "input_image": str(input_image),
        "notes": (
            "Keep the original shelf, camera angle, lighting, product identities, and background unchanged. "
            "Only modify these attributes: positions, promotion labels, prices, and sizes."
        ),
        "skus": perturb_edit_attributes(
            base_payload["skus"],
            seed=seed,
            promotion_count=promotion_count,
        ),
    }


def parse_categories(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    categories: list[str] = []
    for value in values:
        categories.extend(part.strip() for part in value.split(",") if part.strip())
    return categories or None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sample shelf products and build generation/edit request payloads.")
    parser.add_argument("--catalog-file", type=Path, default=DEFAULT_CATALOG_FILE)
    parser.add_argument("--category", "--categories", dest="categories", action="append")
    parser.add_argument("--sample-size", type=int, default=8)
    parser.add_argument("--sample-count", type=int, default=1)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output-file", type=Path, required=True)
    parser.add_argument("--payload-mode", choices=["sample", "generate"], default="sample")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    samples = sample_products(
        categories=parse_categories(args.categories),
        sample_size=args.sample_size,
        sample_count=args.sample_count,
        catalog_file=args.catalog_file,
        seed=args.seed,
    )
    output: Any = samples
    if args.payload_mode == "generate":
        output = [build_generate_payload(sample, seed=args.seed) for sample in samples]
    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output_file": str(args.output_file), "count": len(output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
