from __future__ import annotations

import argparse
import csv
import json
import random
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "generate_image" / "openrouter_shelf_image.py"
DEFAULT_OUTPUT_ROOT = ROOT / "generate_image" / "output" / "runs" / "min_capability" / "all_datasets"
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
REQUEST_SKU_FIELDS = {
    "sku_id",
    "item",
    "category_name",
    "base_price",
    "price",
    "promotion",
    "bestseller_badge",
    "size",
    "flavor",
    "weight",
    "position",
    "product_image",
}
LABEL_FIELDS = ["price", "category_name", "item", "flavor", "size"]
BUDGET_SUBTESTS = {"raw_price", "unit_price"}


@dataclass(frozen=True)
class DatasetConfig:
    slug: str
    category: str
    csv_name: str
    product_term: str
    default_budget: float
    base_price: float
    preferred_brands: tuple[str, ...]
    preferred_flavors: tuple[str, ...]
    preferred_sizes: tuple[str, ...]


DATASETS = [
    DatasetConfig(
        slug="at_home_crackers",
        category="AT HOME CRACKERS",
        csv_name="crackers_sku_list.csv",
        product_term="crackers",
        default_budget=3.00,
        base_price=4.29,
        preferred_brands=("Nabisco", "Pepperidge Farm", "Sunshine", "Ritz"),
        preferred_flavors=("Wheat", "Honey", "Cheese", "Plain"),
        preferred_sizes=("7 oz box", "8.8 oz box", "10 oz box", "13.7 oz box"),
    ),
    DatasetConfig(
        slug="carbonated_soft_drinks",
        category="CARBONATED SOFT DRINKS",
        csv_name="soft_drinks_sku_list.csv",
        product_term="carbonated soft drinks",
        default_budget=4.00,
        base_price=5.99,
        preferred_brands=("Coca-Cola", "Pepsi", "Sprite", "Dr Pepper"),
        preferred_flavors=("Cola", "Diet Cola", "Lemon-Lime", "Dr Pepper"),
        preferred_sizes=("12 fl oz can", "20 fl oz bottle", "2 L bottle", "12 pack cans"),
    ),
    DatasetConfig(
        slug="coffee",
        category="COFFEE",
        csv_name="coffee_sku_list.csv",
        product_term="coffee",
        default_budget=7.00,
        base_price=9.99,
        preferred_brands=("Peet's", "Starbucks", "Folgers", "Yuban"),
        preferred_flavors=("French Roast", "House Blend", "Decaf", "Breakfast Blend"),
        preferred_sizes=("10 oz bag", "12 oz bag", "16 oz bag", "18 ct pods"),
    ),
    DatasetConfig(
        slug="cold_cereal",
        category="COLD CEREAL",
        csv_name="cold_cereal_sku_list.csv",
        product_term="cold cereal",
        default_budget=3.50,
        base_price=4.99,
        preferred_brands=("General Mills", "Kellogg's", "Post", "Quaker"),
        preferred_flavors=("Original", "Honey Nut", "Frosted Wheat", "Cinnamon"),
        preferred_sizes=("10.7 oz box", "12 oz box", "14.8 oz box", "18 oz box"),
    ),
    DatasetConfig(
        slug="tortilla_chips",
        category="TORTILLA CHIPS",
        csv_name="chips_sku_list.csv",
        product_term="tortilla chips",
        default_budget=3.00,
        base_price=4.49,
        preferred_brands=("Tostitos", "Doritos", "Mission", "Santitas"),
        preferred_flavors=("Restaurant Style", "Scoops", "Nacho Cheese", "Hint of Lime"),
        preferred_sizes=("8.5 oz bag", "9.25 oz bag", "10 oz bag", "13 oz bag"),
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and optionally generate minimum-capability shelf images.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument("--datasets", nargs="*", choices=[d.slug for d in DATASETS], help="Dataset slugs to include.")
    parser.add_argument("--scenario-set", choices=["core", "full"], default="full")
    parser.add_argument("--generate", action="store_true", help="Call openrouter_shelf_image.py for each request.")
    parser.add_argument("--limit", type=int, help="Generate at most N images after writing all requests.")
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    parser.add_argument("--attempts", type=int, default=4)
    parser.add_argument("--retry-delay-seconds", type=int, default=60)
    parser.add_argument("--timeout-seconds", type=int, default=600, help="HTTP timeout passed to OpenRouter script.")
    parser.add_argument("--subprocess-timeout-seconds", type=int, default=780)
    parser.add_argument("--model", default=None)
    parser.add_argument("--aspect-ratio", default="4:3")
    parser.add_argument("--image-size", choices=["1K", "2K"], default="1K")
    return parser.parse_args()


def read_rows(config: DatasetConfig) -> list[dict[str, Any]]:
    csv_path = ROOT / "pic_reference" / config.slug / config.csv_name
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["rank_within_category"] = int(float(row["rank_within_category"]))
        row["brand"] = infer_brand(config.slug, row["upc_description"])
        row["flavor"] = infer_flavor(config.slug, row["upc_description"])
        row["size"] = infer_size(config.slug, row["upc_description"], row["rank_within_category"])
        row["weight"] = parse_weight_from_size(row["size"])
        row["category_name"] = row.get("category_name") or config.category
        row["product_image"] = str(find_product_image(config.slug, row) or "")
    return [row for row in rows if row["product_image"]]


def image_sort_key(path: Path) -> tuple[int, int, str]:
    rank = 9999
    stem = path.stem.lower()
    if stem.startswith("rank"):
        digits = ""
        for char in stem[4:]:
            if char.isdigit():
                digits += char
            else:
                break
        if digits:
            rank = int(digits)
    source_priority = 0 if path.parent.name == "images" else 1
    return (rank, source_priority, path.name)


def find_product_image(slug: str, row: dict[str, Any]) -> Path | None:
    base = ROOT / "pic_reference" / slug
    images = sorted(
        [
            path
            for path in base.rglob("*")
            if path.is_file()
            and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
            and "contact_sheet" not in path.name.lower()
        ],
        key=image_sort_key,
    )
    rank = int(row["rank_within_category"])
    upc = str(row.get("upc_a") or row.get("upc_id") or "").lstrip("0")
    exact_upc = [path for path in images if upc and upc in "".join(ch for ch in path.stem if ch.isdigit()).lstrip("0")]
    if exact_upc:
        return exact_upc[0].resolve()
    exact_rank = [path for path in images if path.stem.lower().startswith(f"rank{rank:02d}")]
    if exact_rank:
        return exact_rank[0].resolve()
    return None


def infer_brand(slug: str, description: str) -> str:
    text = " ".join(description.upper().split())
    brand_rules = {
        "at_home_crackers": [
            ("WHEAT THINS", "Nabisco"),
            ("TRISCUIT", "Nabisco"),
            ("RITZ", "Ritz"),
            ("HONEYMAID", "Honey Maid"),
            ("NBC", "Nabisco"),
            ("NABISCO", "Nabisco"),
            ("PEP FARM", "Pepperidge Farm"),
            ("GOLDFISH", "Pepperidge Farm"),
            ("SUNSHINE", "Sunshine"),
            ("CHEEZ-IT", "Sunshine"),
            ("RALSTON", "Ralston"),
        ],
        "carbonated_soft_drinks": [
            ("COCA COLA", "Coca-Cola"),
            ("COKE", "Coca-Cola"),
            ("PEPSI", "Pepsi"),
            ("SPRITE", "Sprite"),
            ("DR PEPPER", "Dr Pepper"),
            ("7UP", "7UP"),
            ("CANADA DRY", "Canada Dry"),
            ("FANTA", "Fanta"),
            ("A&W", "A&W"),
            ("SQUIRT", "Squirt"),
        ],
        "coffee": [
            ("PEETS", "Peet's"),
            ("STARBUCKS", "Starbucks"),
            ("FOLGERS", "Folgers"),
            ("MAXWELL", "Maxwell House"),
            ("YUBAN", "Yuban"),
            ("SEATTLE", "Seattle's Best"),
            ("SFY SEL", "Safeway Select"),
        ],
        "cold_cereal": [
            ("CHEERIOS", "General Mills"),
            ("GM ", "General Mills"),
            ("KLLGG", "Kellogg's"),
            ("KELLOGG", "Kellogg's"),
            ("POST", "Post"),
            ("QUAKER", "Quaker"),
        ],
        "tortilla_chips": [
            ("TOSTITOS", "Tostitos"),
            ("DORITOS", "Doritos"),
            ("MISSION", "Mission"),
            ("LA TAPATIA", "La Tapatia"),
            ("SANTITAS", "Santitas"),
            ("PADRINOS", "Padrinos"),
        ],
    }
    for needle, brand in brand_rules.get(slug, []):
        if needle in text:
            return brand
    return text.split()[0].title() if text else "Unknown"


def infer_flavor(slug: str, description: str) -> str:
    text = " ".join(description.upper().split())
    flavor_rules = {
        "at_home_crackers": [
            ("HONEY", "Honey"),
            ("CHEDDAR", "Cheddar"),
            ("CHEEZ", "Cheese"),
            ("GOLDFISH", "Cheese"),
            ("WHEAT", "Wheat"),
            ("TRISCUIT", "Wheat"),
            ("SALTINE", "Saltine"),
            ("RITZ", "Original"),
        ],
        "carbonated_soft_drinks": [
            ("DIET", "Diet Cola"),
            ("ZERO", "Zero Sugar"),
            ("SPRITE", "Lemon-Lime"),
            ("7UP", "Lemon-Lime"),
            ("DR PEPPER", "Dr Pepper"),
            ("FANTA", "Orange"),
            ("FRESCA", "Citrus"),
            ("PEPSI", "Cola"),
            ("COKE", "Cola"),
            ("COCA COLA", "Cola"),
        ],
        "coffee": [
            ("FRENCH RST", "French Roast"),
            ("FRENCH ROAST", "French Roast"),
            ("HOUSE BLND", "House Blend"),
            ("HOUSE BL", "House Blend"),
            ("BREAKFAST", "Breakfast Blend"),
            ("DECAF", "Decaf"),
            ("ESPRESSO", "Espresso Roast"),
            ("MAJ DICKASON", "Major Dickason"),
            ("MAJOR DICKASON", "Major Dickason"),
            ("TOFFEE", "Toffee"),
        ],
        "cold_cereal": [
            ("HONEY NUT", "Honey Nut"),
            ("HNY", "Honey"),
            ("CINNAMON", "Cinnamon"),
            ("FROSTED", "Frosted Wheat"),
            ("FRSTD", "Frosted Wheat"),
            ("RAISIN", "Raisin Bran"),
            ("GRAPENUT", "Grape-Nuts"),
            ("CHEERIOS", "Original"),
        ],
        "tortilla_chips": [
            ("HINT OF LIME", "Hint of Lime"),
            ("NACHO", "Nacho Cheese"),
            ("COOLER RANCH", "Cool Ranch"),
            ("COOL RANCH", "Cool Ranch"),
            ("TOASTED CORN", "Toasted Corn"),
            ("SCOOPS", "Scoops"),
            ("RESTAURANT STYLE", "Restaurant Style"),
            ("WHITE CORN", "White Corn"),
            ("WHT CORN", "White Corn"),
            ("BITE SIZE", "Bite Size"),
            ("GOLD", "Yellow Corn"),
        ],
    }
    for needle, flavor in flavor_rules.get(slug, []):
        if needle in text:
            return flavor
    return "Original"


def parse_weight_from_size(size: str) -> float | None:
    text = str(size or "").lower()
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    amount = float(match.group(1))
    if "pack" in text and ("12" in text or "can" in text):
        can_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:fl\s*)?oz", text)
        if can_match:
            return round(float(can_match.group(1)) * amount, 2)
        return round(12.0 * amount, 2)
    if " l" in f" {text}" or text.endswith("l bottle") or "liter" in text:
        return round(amount * 33.814, 2)
    if "ct" in text or "count" in text or "pods" in text:
        return amount
    return amount


def money(value: float) -> str:
    return f"${value:.2f}"


def money_to_float(value: Any) -> float:
    return float(str(value).replace("$", ""))


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def row_base_price(config: DatasetConfig, row: dict[str, Any]) -> float:
    item_qty = as_float(row.get("item_qty"))
    gross_amt = as_float(row.get("gross_amt"))
    net_amt = as_float(row.get("net_amt"))
    if item_qty and item_qty > 0:
        amount = gross_amt if gross_amt and gross_amt > 0 else net_amt
        if amount and amount > 0:
            return max(0.49, amount / item_qty)
    return config.base_price


def random_money_offsets(rng: random.Random, count: int, low: float, high: float) -> list[float]:
    offsets: set[float] = set()
    while len(offsets) < count:
        offsets.add(round(rng.uniform(low, high), 2))
    return sorted(offsets)


def positions() -> list[dict[str, int]]:
    return [{"row": row, "col": col} for row in (1, 2) for col in (1, 2, 3, 4)]


def shelf_sku(
    config: DatasetConfig,
    row: dict[str, Any],
    index: int,
    price: float,
    base_price: float | None = None,
    size: str | None = None,
    weight: float | None = None,
    sku_suffix: str = "",
) -> dict[str, Any]:
    size_value = size or row["size"]
    weight_value = weight if weight is not None else row["weight"]
    return {
        "sku_id": f"{row.get('upc_id') or row.get('upc_a')}{sku_suffix}",
        "item": row["upc_description"],
        "category_name": config.category,
        "base_price": money(base_price if base_price is not None else price),
        "price": money(price),
        "promotion": "none",
        "bestseller_badge": "none",
        "size": size_value,
        "flavor": row["flavor"],
        "weight": round(float(weight_value), 2),
        "position": positions()[index - 1],
        "product_image": row["product_image"],
    }


def infer_size(slug: str, description: str, rank: int = 1) -> str:
    text = description.upper()
    if slug == "carbonated_soft_drinks":
        if "FRDG" in text or "FRIDGE" in text:
            return "12 pack cans"
        sizes = ("12 fl oz can", "20 fl oz bottle", "2 L bottle")
        return sizes[(rank - 1) % len(sizes)]
    if slug == "coffee":
        sizes = ("10 oz bag", "12 oz bag", "16 oz bag", "18 ct pods")
        return sizes[(rank - 1) % len(sizes)]
    if slug == "cold_cereal":
        if "BT SZ" in text or "BIG" in text:
            return "18 oz box"
        sizes = ("10.7 oz box", "12 oz box", "14.8 oz box", "18 oz box")
        return sizes[(rank - 1) % len(sizes)]
    if slug == "at_home_crackers":
        sizes = ("7 oz box", "8.8 oz box", "10 oz box", "13.7 oz box")
        return sizes[(rank - 1) % len(sizes)]
    if "FAMILY SIZE" in text:
        return "13 oz bag"
    sizes = ("8.5 oz bag", "9.25 oz bag", "10 oz bag", "13 oz bag")
    return sizes[(rank - 1) % len(sizes)]


def payload(
    config: DatasetConfig,
    scenario_id: str,
    test_group: str,
    subtest: str,
    prompt_instruction: str,
    skus: list[dict[str, Any]],
    correct_sku_id: str,
    label_fields: list[str],
    target_field: str | None = None,
    target_value: str | None = None,
    target_relation: str | None = None,
) -> dict[str, Any]:
    task_family = "budget" if subtest in BUDGET_SUBTESTS else subtest
    item = {
        "mode": "generate",
        "category": config.category,
        "layout": {"rows": 2, "cols": 4},
        "sample_index": scenario_id,
        "style": "realistic 2 by 4 grocery shelf experiment image",
        "notes": (
            "Create exactly eight focal products arranged in a two-row by four-column supermarket shelf grid. "
            "This is a minimum-capability product-choice experiment; make shelf tags and decision labels large, crisp, and readable. "
            "Do not render any shopper instruction, task title, banner, headline, or explanatory text in the scene; "
            "only render the product packages and their shelf tags."
        ),
        "test_group": test_group,
        "experiment": task_family,
        "task_family": task_family,
        "subtest": subtest,
        "scenario_id": scenario_id,
        "prompt_instruction": prompt_instruction,
        "correct_sku_id": correct_sku_id,
        "experiment_label_fields": label_fields,
        "skus": skus,
    }
    if target_field and target_value:
        item["target_field"] = target_field
        item["target_value"] = target_value
    if target_relation:
        item["target_relation"] = target_relation
    return item


def choose_rows(rows: list[dict[str, Any]], target_key: str, target_value: str, rng: random.Random) -> list[dict[str, Any]]:
    targets = [row for row in rows if row[target_key] == target_value]
    non_targets = [row for row in rows if row[target_key] != target_value]
    if not targets or len(non_targets) < 7:
        raise ValueError(f"Cannot build unique {target_key}={target_value} scenario.")
    chosen = [targets[0]] + non_targets[:7]
    rng.shuffle(chosen)
    return chosen


def choose_size_rows(
    rows: list[dict[str, Any]],
    target_size: str,
    relation: str,
    rng: random.Random,
) -> list[dict[str, Any]]:
    target_weight = parse_weight_from_size(target_size)
    if target_weight is None:
        raise ValueError(f"Cannot parse size threshold: {target_size}")
    weighted = rows_with_weight(rows)
    if relation == "greater_than":
        targets = [row for row in weighted if float(row["weight"]) > target_weight]
        non_targets = [row for row in weighted if float(row["weight"]) <= target_weight]
    elif relation == "less_than":
        targets = [row for row in weighted if float(row["weight"]) < target_weight]
        non_targets = [row for row in weighted if float(row["weight"]) >= target_weight]
    else:
        raise ValueError(f"Unsupported size relation: {relation}")
    if not targets or len(non_targets) < 7:
        raise ValueError(f"Cannot build unique size {relation} {target_size} scenario.")
    chosen = [targets[0]] + non_targets[:7]
    rng.shuffle(chosen)
    return chosen


def available_unique_values(
    rows: list[dict[str, Any]],
    key: str,
    preferred: tuple[str, ...],
    needed: int,
) -> list[str]:
    values = []
    counts = {row[key]: 0 for row in rows}
    for row in rows:
        counts[row[key]] += 1
    ordered = list(preferred) + sorted(value for value in counts if value not in preferred)
    for value in ordered:
        if counts.get(value, 0) >= 1 and len(rows) - counts.get(value, 0) >= 7:
            values.append(value)
        if len(values) >= needed:
            break
    return values


def available_size_thresholds(
    rows: list[dict[str, Any]],
    preferred: tuple[str, ...],
    relation: str,
    needed: int,
) -> list[str]:
    weighted = rows_with_weight(rows)
    sizes = {row["size"] for row in weighted}
    ordered = list(preferred) + sorted(sizes - set(preferred), key=lambda size: parse_weight_from_size(size) or 0)
    values = []
    for size in ordered:
        threshold = parse_weight_from_size(size)
        if threshold is None:
            continue
        if relation == "greater_than":
            target_count = sum(1 for row in weighted if float(row["weight"]) > threshold)
            non_target_count = sum(1 for row in weighted if float(row["weight"]) <= threshold)
        elif relation == "less_than":
            target_count = sum(1 for row in weighted if float(row["weight"]) < threshold)
            non_target_count = sum(1 for row in weighted if float(row["weight"]) >= threshold)
        else:
            raise ValueError(f"Unsupported size relation: {relation}")
        if target_count >= 1 and non_target_count >= 7:
            values.append(size)
        if len(values) >= needed:
            break
    return values


def budget_threshold_values(
    budget: float,
    target_index: int,
    count: int,
    rng: random.Random,
) -> list[float]:
    target_discount = rng.random() * budget
    distractor_values = [budget + offset for offset in random_money_offsets(rng, count - 1, 0.05, 1.80)]
    rng.shuffle(distractor_values)
    values: list[float] = []
    for index in range(count):
        values.append(budget - target_discount if index == target_index else distractor_values.pop())
    return values


def choose_budget_rows(
    config: DatasetConfig,
    rows: list[dict[str, Any]],
    variant: int,
    rng: random.Random,
) -> tuple[list[dict[str, Any]], int, float]:
    chosen = rows[variant : variant + 8]
    if len(chosen) < 8:
        chosen = rows[:8]
    rng.shuffle(chosen)
    budget = config.default_budget + 0.50 * variant
    target_index = rng.randrange(len(chosen))
    return chosen, target_index, budget


def instruction_attribute_scenario(
    config: DatasetConfig,
    rows: list[dict[str, Any]],
    subtest: str,
    value: str,
    variant: int,
    rng: random.Random,
) -> dict[str, Any]:
    key = subtest
    chosen = choose_rows(rows, key, value, rng)
    skus = []
    correct_id = ""
    for index, row in enumerate(chosen, start=1):
        price = row_base_price(config, row)
        item = shelf_sku(
            config,
            row,
            index,
            price=price,
        )
        skus.append(item)
        if row[key] == value:
            correct_id = item["sku_id"]
    prompt_templates = {
        "brand": f"Choose the {config.product_term} product from brand {value}.",
        "flavor": f"Choose the {config.product_term} product with {value} flavor.",
        "size": f"Choose the {config.product_term} product in size {value}.",
    }
    return payload(
        config=config,
        scenario_id=f"{config.slug}_{subtest}_{variant + 1}",
        test_group="instruction_following",
        subtest=subtest,
        prompt_instruction=prompt_templates[subtest],
        skus=skus,
        correct_sku_id=correct_id,
        label_fields=LABEL_FIELDS.copy(),
        target_field=key,
        target_value=value,
    )


def instruction_size_scenario(
    config: DatasetConfig,
    rows: list[dict[str, Any]],
    target_size: str,
    relation: str,
    variant: int,
    rng: random.Random,
) -> dict[str, Any]:
    chosen = choose_size_rows(rows, target_size, relation, rng)
    skus = []
    correct_id = ""
    target_weight = parse_weight_from_size(target_size)
    if target_weight is None:
        raise ValueError(f"Cannot parse size threshold: {target_size}")
    for index, row in enumerate(chosen, start=1):
        price = row_base_price(config, row)
        item = shelf_sku(config, row, index, price=price)
        skus.append(item)
        weight = float(row["weight"])
        if relation == "greater_than" and weight > target_weight:
            correct_id = item["sku_id"]
        elif relation == "less_than" and weight < target_weight:
            correct_id = item["sku_id"]
    relation_text = "larger than" if relation == "greater_than" else "smaller than"
    return payload(
        config=config,
        scenario_id=f"{config.slug}_size_{variant + 1}",
        test_group="instruction_following",
        subtest="size",
        prompt_instruction=f"Choose the {config.product_term} product with size {relation_text} {target_size}.",
        skus=skus,
        correct_sku_id=correct_id,
        label_fields=LABEL_FIELDS.copy(),
        target_field="size",
        target_value=target_size,
        target_relation=relation,
    )


def article(word: str) -> str:
    return "an" if word[:1].lower() in {"a", "e", "i", "o", "u"} else "a"


def instruction_raw_price_scenario(
    config: DatasetConfig,
    rows: list[dict[str, Any]],
    variant: int,
    rng: random.Random,
) -> dict[str, Any]:
    chosen, target_index, budget = choose_budget_rows(config, rows, variant, rng)
    prices = budget_threshold_values(budget, target_index, len(chosen), rng)
    skus = []
    correct_id = ""
    for index, (row, raw_price) in enumerate(zip(chosen, prices), start=1):
        item = shelf_sku(config, row, index, price=raw_price, base_price=raw_price)
        skus.append(item)
        if index - 1 == target_index:
            correct_id = item["sku_id"]
    return payload(
        config=config,
        scenario_id=f"{config.slug}_raw_price_{variant + 1}",
        test_group="instruction_following",
        subtest="raw_price",
        prompt_instruction=f"Choose the {config.product_term} product with raw shelf price at or below {money(budget)}.",
        skus=skus,
        correct_sku_id=correct_id,
        label_fields=LABEL_FIELDS.copy(),
        target_field="base_price",
        target_value=money(budget),
    )


def rows_with_weight(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("weight") not in (None, "") and float(row["weight"]) > 0]


def size_weight_options(config: DatasetConfig, variant: int) -> list[str]:
    if config.slug == "carbonated_soft_drinks":
        options = [
            "8 fl oz can",
            "12 fl oz can",
            "16 fl oz can",
            "20 fl oz bottle",
            "1 L bottle",
            "1.25 L bottle",
            "1.5 L bottle",
            "2 L bottle",
        ]
    elif config.slug == "coffee":
        options = ["8 oz bag", "10 oz bag", "12 oz bag", "14 oz bag", "16 oz bag", "18 oz bag", "20 oz bag", "24 oz bag"]
    elif config.slug == "cold_cereal":
        options = ["8.9 oz box", "10.7 oz box", "12 oz box", "13.5 oz box", "14.8 oz box", "16 oz box", "18 oz box", "21 oz box"]
    elif config.slug == "at_home_crackers":
        options = ["6 oz box", "7 oz box", "8 oz box", "8.8 oz box", "10 oz box", "12 oz box", "13.7 oz box", "16 oz box"]
    else:
        options = ["7 oz bag", "8.5 oz bag", "9.25 oz bag", "10 oz bag", "11 oz bag", "12 oz bag", "13 oz bag", "15 oz bag"]
    if variant % 2:
        return list(reversed(options))
    return options


def instruction_unit_price_scenario(
    config: DatasetConfig,
    rows: list[dict[str, Any]],
    variant: int,
    rng: random.Random,
) -> dict[str, Any]:
    weighted = rows_with_weight(rows)
    if len(weighted) < 8:
        raise ValueError(f"{config.slug} has only {len(weighted)} SKU rows with parseable weight.")
    chosen, target_index, budget = choose_budget_rows(config, weighted, variant, rng)
    unit_prices = budget_threshold_values(budget, target_index, len(chosen), rng)
    skus = []
    correct_id = ""
    for index, (row, unit_price) in enumerate(zip(chosen, unit_prices), start=1):
        raw_price = round(float(row["weight"]) * unit_price, 2)
        item = shelf_sku(config, row, index, price=raw_price, base_price=raw_price)
        skus.append(item)
        if index - 1 == target_index:
            correct_id = item["sku_id"]
    return payload(
        config=config,
        scenario_id=f"{config.slug}_unit_price_{variant + 1}",
        test_group="instruction_following",
        subtest="unit_price",
        prompt_instruction=f"Choose the {config.product_term} product with unit price at or below {money(budget)}. Unit price is raw price divided by weight.",
        skus=skus,
        correct_sku_id=correct_id,
        label_fields=LABEL_FIELDS.copy(),
        target_field="unit_price",
        target_value=money(budget),
    )


def price_scenario(
    config: DatasetConfig,
    row: dict[str, Any],
    scenario_name: str,
    prices: list[float],
    rng: random.Random,
) -> dict[str, Any]:
    order = list(range(8))
    rng.shuffle(order)
    shuffled_prices = [prices[i] for i in order]
    min_price = min(shuffled_prices)
    skus = []
    correct_id = ""
    for index, price in enumerate(shuffled_prices, start=1):
        item = shelf_sku(config, row, index, price=price, sku_suffix=f"-P{index}")
        skus.append(item)
        if price == min_price:
            correct_id = item["sku_id"]
    return payload(
        config=config,
        scenario_id=f"{config.slug}_price_{scenario_name}",
        test_group="basic_rationality",
        subtest="price",
        prompt_instruction=f"Choose the lowest-priced {config.product_term} option. The products are otherwise identical.",
        skus=skus,
        correct_sku_id=correct_id,
        label_fields=LABEL_FIELDS.copy(),
        target_field="price",
        target_value="lowest",
    )


def size_weight_scenario(
    config: DatasetConfig,
    row: dict[str, Any],
    scenario_name: str,
    sizes: list[str],
    rng: random.Random,
) -> dict[str, Any]:
    weighted_sizes = [(size, parse_weight_from_size(size)) for size in sizes]
    weighted_sizes = [(size, weight) for size, weight in weighted_sizes if weight is not None and weight > 0]
    if len(weighted_sizes) != 8:
        raise ValueError(f"{config.slug} size_weight scenario needs 8 parseable sizes.")
    rng.shuffle(weighted_sizes)
    max_weight = max(weight for _, weight in weighted_sizes)
    skus = []
    correct_id = ""
    for index, (size, weight) in enumerate(weighted_sizes, start=1):
        item = shelf_sku(
            config,
            row,
            index,
            price=config.base_price,
            base_price=config.base_price,
            size=size,
            weight=weight,
            sku_suffix=f"-S{index}",
        )
        skus.append(item)
        if weight == max_weight:
            correct_id = item["sku_id"]
    return payload(
        config=config,
        scenario_id=f"{config.slug}_size_weight_{scenario_name}",
        test_group="basic_rationality",
        subtest="size_weight",
        prompt_instruction=f"Choose the {config.product_term} option with the largest weight. The options have the same price.",
        skus=skus,
        correct_sku_id=correct_id,
        label_fields=LABEL_FIELDS.copy(),
        target_field="weight",
        target_value="largest",
    )


def build_payloads(
    config: DatasetConfig,
    rows: list[dict[str, Any]],
    scenario_set: str,
    rng: random.Random,
    price_anchor_index: int = 0,
) -> list[dict[str, Any]]:
    scenario_count = 2 if scenario_set == "full" else 1
    payloads: list[dict[str, Any]] = []

    brands = available_unique_values(rows, "brand", config.preferred_brands, scenario_count)
    flavors = available_unique_values(rows, "flavor", config.preferred_flavors, scenario_count)
    for variant, brand in enumerate(brands):
        payloads.append(instruction_attribute_scenario(config, rows, "brand", brand, variant, rng))
    for variant, flavor in enumerate(flavors):
        payloads.append(instruction_attribute_scenario(config, rows, "flavor", flavor, variant, rng))
    for variant in range(scenario_count):
        relation = "greater_than" if variant % 2 == 0 else "less_than"
        thresholds = available_size_thresholds(rows, config.preferred_sizes, relation, 1)
        if not thresholds:
            raise ValueError(f"Cannot build size {relation} scenario for {config.slug}.")
        payloads.append(instruction_size_scenario(config, rows, thresholds[0], relation, variant, rng))
    for variant in range(scenario_count):
        payloads.append(instruction_raw_price_scenario(config, rows, variant, rng))
        payloads.append(instruction_unit_price_scenario(config, rows, variant, rng))

    if not 0 <= price_anchor_index < len(rows):
        raise ValueError(f"price_anchor_index={price_anchor_index} is out of range for {config.slug}; rows={len(rows)}")
    anchor = rows[price_anchor_index]
    base = config.base_price
    price_variants = {
        "adjusted_low": [base - 0.03, base + 0.02, base + 0.04, base + 0.05, base + 0.06, base + 0.07, base + 0.08, base + 0.09],
        "adjusted_high": [base - 1.20, base - 0.55, base - 0.15, base + 0.25, base + 0.80, base + 1.15, base + 1.60, base + 2.10],
    }
    if scenario_set == "core":
        price_variants = {"adjusted_low": price_variants["adjusted_low"]}
    for name, prices in price_variants.items():
        payloads.append(price_scenario(config, anchor, name, prices, rng))
    for variant in range(scenario_count):
        payloads.append(size_weight_scenario(config, anchor, f"same_price_largest_{variant + 1}", size_weight_options(config, variant), rng))
    return payloads


def validate_payload(item: dict[str, Any]) -> None:
    skus = item["skus"]
    if len(skus) != 8:
        raise ValueError(f"{item['scenario_id']} has {len(skus)} SKUs, expected 8.")
    for sku in skus:
        fields = set(sku)
        if fields != REQUEST_SKU_FIELDS:
            extra = sorted(fields - REQUEST_SKU_FIELDS)
            missing = sorted(REQUEST_SKU_FIELDS - fields)
            raise ValueError(f"{item['scenario_id']} has invalid SKU fields. extra={extra}, missing={missing}")
    correct = [sku for sku in skus if sku["sku_id"] == item["correct_sku_id"]]
    if len(correct) != 1:
        raise ValueError(f"{item['scenario_id']} does not have exactly one correct SKU id.")
    subtest = item["subtest"]
    if subtest == "brand":
        target = item["target_value"]
        dataset = item["scenario_id"].split("_brand", 1)[0]
        winners = [sku for sku in skus if infer_brand(dataset, sku["item"]) == target]
    elif subtest == "flavor":
        target = item["target_value"]
        winners = [sku for sku in skus if sku[subtest] == target]
    elif subtest == "size":
        target_weight = parse_weight_from_size(item["target_value"])
        if target_weight is None:
            raise ValueError(f"{item['scenario_id']} has unparseable target size: {item['target_value']}")
        relation = item.get("target_relation")
        if relation == "greater_than":
            winners = [sku for sku in skus if float(sku["weight"]) > target_weight]
        elif relation == "less_than":
            winners = [sku for sku in skus if float(sku["weight"]) < target_weight]
        else:
            raise ValueError(f"{item['scenario_id']} has invalid size relation: {relation}")
    elif subtest == "raw_price":
        limit = money_to_float(item["target_value"])
        winners = [sku for sku in skus if money_to_float(sku["base_price"]) <= limit]
    elif subtest == "unit_price":
        limit = money_to_float(item["target_value"])
        winners = [sku for sku in skus if money_to_float(sku["base_price"]) / float(sku["weight"]) <= limit]
    elif subtest == "price":
        min_price = min(money_to_float(sku["price"]) for sku in skus)
        winners = [sku for sku in skus if money_to_float(sku["price"]) == min_price]
    elif subtest == "size_weight":
        prices = {sku["price"] for sku in skus}
        if len(prices) != 1:
            raise ValueError(f"{item['scenario_id']} size_weight must keep price fixed.")
        max_weight = max(float(sku["weight"]) for sku in skus)
        winners = [sku for sku in skus if float(sku["weight"]) == max_weight]
    else:
        raise ValueError(f"Unknown subtest: {subtest}")
    if len(winners) != 1 or winners[0]["sku_id"] != item["correct_sku_id"]:
        raise ValueError(f"{item['scenario_id']} has invalid winner set: {[sku['sku_id'] for sku in winners]}")


def write_requests(output_root: Path, all_payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for item in all_payloads:
        validate_payload(item)
        dataset = item["scenario_id"].split("_" + item["subtest"], 1)[0]
        correct_product_number = next(
            index for index, sku in enumerate(item["skus"], start=1) if sku["sku_id"] == item["correct_sku_id"]
        )
        case_dir = output_root / dataset / item["test_group"] / item["task_family"] / item["subtest"]
        request_file = case_dir / "requests" / f"{item['scenario_id']}.json"
        screen_file = case_dir / "screens" / f"{item['scenario_id']}.png"
        request_file.parent.mkdir(parents=True, exist_ok=True)
        screen_file.parent.mkdir(parents=True, exist_ok=True)
        request_file.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest.append(
            {
                "dataset": dataset,
                "category": item["category"],
                "scenario_id": item["scenario_id"],
                "test_group": item["test_group"],
                "experiment": item["experiment"],
                "task_family": item["task_family"],
                "subtest": item["subtest"],
                "scene_type": "realistic_2x4_grocery_shelf",
                "prompt_instruction": item["prompt_instruction"],
                "target_field": item.get("target_field"),
                "target_value": item.get("target_value"),
                "target_relation": item.get("target_relation"),
                "correct_sku_id": item["correct_sku_id"],
                "correct_product_number": correct_product_number,
                "request_file": str(request_file),
                "screen_file": str(screen_file),
                "skus": item["skus"],
            }
        )
    (output_root / "manifest.json").write_text(
        json.dumps({"output_root": str(output_root), "count": len(manifest), "items": manifest}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def run_generation(args: argparse.Namespace, manifest: list[dict[str, Any]]) -> None:
    selected = manifest[: args.limit] if args.limit else manifest
    for index, item in enumerate(selected, start=1):
        output = Path(item["screen_file"])
        if args.skip_existing and output.exists() and output.stat().st_size > 0:
            print(f"[{index}/{len(selected)}] skip existing {output}")
            continue
        cmd = [
            sys.executable,
            str(SCRIPT),
            "--request-file",
            item["request_file"],
            "--output-file",
            item["screen_file"],
            "--allow-missing-product-images",
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
        for attempt in range(1, args.attempts + 1):
            print(f"[{index}/{len(selected)}] generate {item['scenario_id']} attempt {attempt}/{args.attempts}")
            try:
                subprocess.run(cmd, check=True, timeout=args.subprocess_timeout_seconds)
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                if attempt >= args.attempts:
                    raise RuntimeError(f"Generation failed for {item['scenario_id']}") from exc
                print(f"Retrying in {args.retry_delay_seconds}s after: {exc}")
                time.sleep(args.retry_delay_seconds)


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    selected_slugs = set(args.datasets or [config.slug for config in DATASETS])
    all_payloads = []
    for config in DATASETS:
        if config.slug not in selected_slugs:
            continue
        rows = read_rows(config)
        if len(rows) < 8:
            raise ValueError(f"{config.slug} has only {len(rows)} SKU rows with images.")
        all_payloads.extend(build_payloads(config, rows, args.scenario_set, rng))
    manifest = write_requests(args.output_root, all_payloads)
    print(json.dumps({"output_root": str(args.output_root), "requests": len(manifest)}, ensure_ascii=False, indent=2))
    if args.generate:
        run_generation(args, manifest)


if __name__ == "__main__":
    main()
