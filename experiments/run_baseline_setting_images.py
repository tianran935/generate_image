from __future__ import annotations

import argparse
import copy
import os
import json
import random
import subprocess
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .build_min_capability_requests import (
        DATASETS,
        REQUEST_SKU_FIELDS,
        SCRIPT,
        build_payloads,
        read_rows,
        validate_payload,
    )
except ImportError:
    from build_min_capability_requests import (
        DATASETS,
        REQUEST_SKU_FIELDS,
        SCRIPT,
        build_payloads,
        read_rows,
        validate_payload,
    )


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = ROOT / "generate_image" / "output" / "runs" / "baseline_setting"
DEFAULT_EXPERIMENTS = ("budget", "brand", "flavor", "size", "raw_price", "unit_price", "price", "size_weight")
ALL_EXPERIMENTS = DEFAULT_EXPERIMENTS
DATASET_BY_SLUG = {config.slug: config for config in DATASETS}
EXPECTED_POSITIONS = {
    1: {"row": 1, "col": 1},
    2: {"row": 1, "col": 2},
    3: {"row": 1, "col": 3},
    4: {"row": 1, "col": 4},
    5: {"row": 2, "col": 1},
    6: {"row": 2, "col": 2},
    7: {"row": 2, "col": 3},
    8: {"row": 2, "col": 4},
}
DESIGN_LABEL_FIELDS = ["price", "category_name", "item", "flavor", "size"]
DESIGN_GENERATE_NOTES = (
    "Create exactly eight focal products arranged in a strict two-row by four-column supermarket shelf grid. "
    "Use the fixed row and column position specified for each SKU in the structured request. "
    "Each target cell must contain exactly one visible focal product unit: no duplicate facings, no stacks, no repeated copies "
    "of the same focal SKU inside a cell, no empty option cells, and no extra focal products. "
    "Do not use empty space, shelf fullness, product quantity, or display depth to express any variable. "
    "Render one physical supermarket shelf tag directly below each focal product, attached to the shelf rail and centered under that product. "
    "The shelf tag must look like a real paper supermarket price tag, not an e-commerce card, web UI, button, table, or floating overlay. "
    "Each tag must stay inside its own cell, must not overlap neighboring tags, and must not cover the product package body. "
    "Every main shelf tag must show price with two decimals, category name, a short item name when space allows, flavor, and size. "
    "Do not print product_number, option number, #1-#8 markers, row/column numbers, or SKU IDs on the shelf tags or product packages. "
    "Product numbers are internal request and manifest keys only. "
    "Use high-contrast black horizontal text on a white, light gray, or light yellow tag. "
    "Do not write the shopper instruction, task title, banner, headline, or explanatory text anywhere in the image. "
    "Promotion and bestseller fields are fixed to none in this baseline run, so do not render any promotion sticker, sale sticker, bestseller badge, hot badge, or top-pick marker."
)
DESIGN_EDIT_NOTES = (
    "Edit the provided baseline shelf image while preserving the shelf framing, camera angle, lighting, background, package identities, "
    "fixed 2x4 positions, and all non-target attributes. Keep exactly one visible focal product unit in each of the eight cells. "
    "Keep the physical shelf tags directly below the corresponding products, with two-decimal price, category name, short item name when space allows, flavor, size, high-contrast horizontal text, and no overlapping tags. "
    "Do not print product_number, option number, #1-#8 markers, row/column numbers, or SKU IDs on the shelf tags or product packages. "
    "Change only the structured target values needed for this scenario, especially the shelf price labels. "
    "Prices must remain two-decimal values and must be readable, including 1 percent price-difference scenarios. "
    "Do not add shopper instructions, banners, promotion stickers, sale stickers, bestseller badges, hot badges, or top-pick markers."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build and optionally generate Baseline Setting shelf images. "
            "All Baseline Setting items are edit requests against a user-provided baseline image."
        )
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument("--datasets", nargs="*", choices=[config.slug for config in DATASETS])
    parser.add_argument("--scenario-set", choices=["core", "full", "all"], default="full")
    parser.add_argument("--price-anchor-index", type=int, default=0, help="Zero-based row index of the SKU to use as the identical-option price anchor.")
    parser.add_argument(
        "--experiments",
        nargs="*",
        choices=ALL_EXPERIMENTS,
        default=list(DEFAULT_EXPERIMENTS),
        help="Baseline experiments to include. Defaults to the four Baseline Setting experiments.",
    )
    parser.add_argument(
        "--edit-source",
        choices=["first", "previous"],
        default="first",
        help="Compatibility metadata only; Baseline Setting is edit-only and always uses --baseline-image.",
    )
    parser.add_argument(
        "--edit-source-scope",
        choices=["dataset", "experiment", "run"],
        default="experiment",
        help=(
            "Compatibility metadata only; Baseline Setting is edit-only and every item uses --baseline-image."
        ),
    )
    parser.add_argument(
        "--original-image",
        "--baseline-image",
        dest="original_image",
        type=Path,
        help="Required baseline shelf image to use as the edit source for every item.",
    )
    parser.add_argument("--original-request-file", type=Path, help="Optional request JSON for the original image; used to populate base_skus for edit diffs.")
    parser.add_argument("--generate", action="store_true", help="Call openrouter_shelf_image.py after writing requests.")
    parser.add_argument("--limit", type=int, help="Generate at most N manifest items after writing all requests.")
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume from existing status/output files.")
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--retry-failed-only", action="store_true", help="Only rerun items previously marked failed/blocked or missing an output image.")
    parser.add_argument("--keep-going", action="store_true", default=True, help="Continue after per-image failures.")
    parser.add_argument("--fail-fast", dest="keep_going", action="store_false", help="Stop on the first failed or blocked image.")
    parser.add_argument("--status-file", type=Path, help="Checkpoint JSON path. Defaults to <output-root>/run_status.json.")
    parser.add_argument("--events-file", type=Path, help="JSONL event log path. Defaults to <output-root>/run_events.jsonl.")
    parser.add_argument("--log-dir", type=Path, help="Per-attempt stdout/stderr log directory. Defaults to <output-root>/logs.")
    parser.add_argument(
        "--workers",
        type=int,
        help="Maximum concurrent image-generation subprocesses. Defaults to the number of loaded API keys, or 1.",
    )
    parser.add_argument("--api-key-file", type=Path, help="Text file containing one OpenRouter API key per line.")
    parser.add_argument("--api-key-env", default="OPENROUTER_API_KEYS", help="Environment variable containing comma/newline-separated OpenRouter API keys.")
    parser.add_argument("--min-delay-per-key-seconds", type=float, default=0.0, help="Minimum delay between request starts for the same API key.")
    parser.add_argument("--max-in-flight-per-key", type=int, default=1, help="Maximum concurrent subprocesses using the same API key.")
    parser.add_argument("--attempts", type=int, default=4)
    parser.add_argument("--retry-delay-seconds", type=int, default=60)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--subprocess-timeout-seconds", type=int, default=780)
    parser.add_argument("--model")
    parser.add_argument("--aspect-ratio", default="4:3")
    parser.add_argument("--image-size", choices=["1K", "2K"], default="1K")
    parser.add_argument("--allow-missing-product-images", action="store_true")
    parser.add_argument("--send-individual-product-images", action="store_true")
    return parser.parse_args()


def selected_experiments(args: argparse.Namespace) -> set[str]:
    return set(args.experiments)


def dataset_from_scenario_id(payload: dict[str, Any]) -> str:
    return payload["scenario_id"].split("_" + payload["subtest"], 1)[0]


def strip_unused_controls(payload: dict[str, Any]) -> None:
    for sku in payload["skus"]:
        sku["promotion"] = "none"
        sku["bestseller_badge"] = "none"
        sku.pop("inventory_remaining", None)
    payload.pop("inventory_visual_strategy", None)
    payload.pop("inventory_control", None)


def label_fields_for(subtest: str) -> list[str]:
    return DESIGN_LABEL_FIELDS.copy()


def baseline_family(subtest: str) -> str:
    return "identical_option" if subtest in {"price", "size_weight"} else "assortment"


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(payload)
    normalized["mode"] = "generate"
    normalized["baseline_setting"] = True
    normalized["baseline_family"] = baseline_family(normalized["subtest"])
    normalized["experiment_label_fields"] = label_fields_for(normalized["subtest"])
    normalized["notes"] = DESIGN_GENERATE_NOTES
    normalized["design_requirements_source"] = "generate_image/docs/design.md"
    normalized["design_requirements"] = {
        "layout": "strict 2x4, exactly eight focal products",
        "position_map": EXPECTED_POSITIONS,
        "cell_quantity_rule": "one visible focal product unit per cell",
        "main_shelf_tag_fields": DESIGN_LABEL_FIELDS,
        "internal_only_fields": ["product_number", "sku_id"],
        "reference_sheet_only": True,
        "formal_product_image_policy": "product_image must exist for every SKU",
        "aspect_ratio": "4:3",
        "image_size": "1K",
        "promotion": "none; no promotion sticker",
        "bestseller_badge": "none; no bestseller sticker",
        "forbidden_visual_variables": ["inventory", "empty space", "shelf fullness", "facings", "stacking"],
        "forbidden_text": "no shopper instruction, task title, banner, explanatory text, product_number, option number, row/column number, or SKU ID in image",
    }
    strip_unused_controls(normalized)
    validate_design_payload(normalized)
    validate_payload(normalized)
    return normalized


def validate_design_payload(payload: dict[str, Any]) -> None:
    skus = payload["skus"]
    if payload.get("layout") != {"rows": 2, "cols": 4}:
        raise ValueError(f"{payload['scenario_id']} must use layout rows=2, cols=4.")
    if len(skus) != 8:
        raise ValueError(f"{payload['scenario_id']} must contain exactly 8 SKUs.")
    for number, sku in enumerate(skus, start=1):
        expected = EXPECTED_POSITIONS[number]
        if sku.get("position") != expected:
            raise ValueError(
                f"{payload['scenario_id']} has invalid position for product #{number}: "
                f"{sku.get('position')} != {expected}"
            )
        fields = set(sku)
        if fields != REQUEST_SKU_FIELDS:
            extra = sorted(fields - REQUEST_SKU_FIELDS)
            missing = sorted(REQUEST_SKU_FIELDS - fields)
            raise ValueError(f"{payload['scenario_id']} SKU #{number} has invalid fields. extra={extra}, missing={missing}")
        for required in REQUEST_SKU_FIELDS:
            if required not in sku or sku[required] in (None, ""):
                raise ValueError(f"{payload['scenario_id']} SKU #{number} missing required field {required}.")
        if sku.get("promotion") != "none":
            raise ValueError(f"{payload['scenario_id']} SKU #{number} promotion must be none.")
        if sku.get("bestseller_badge") != "none":
            raise ValueError(f"{payload['scenario_id']} SKU #{number} bestseller_badge must be none.")
        if "inventory_remaining" in sku:
            raise ValueError(f"{payload['scenario_id']} SKU #{number} must not include inventory_remaining.")
        if "color" in sku:
            raise ValueError(f"{payload['scenario_id']} SKU #{number} must not include color.")
        if "rating" in sku or "reviews" in sku or "number_of_reviews" in sku:
            raise ValueError(f"{payload['scenario_id']} SKU #{number} must not include rating/review fields.")
        if not str(sku["price"]).startswith("$") or len(str(sku["price"]).rsplit(".", 1)[-1]) != 2:
            raise ValueError(f"{payload['scenario_id']} SKU #{number} price must use two decimal places: {sku['price']}")
        if not Path(str(sku["product_image"])).exists():
            raise FileNotFoundError(f"{payload['scenario_id']} SKU #{number} product_image not found: {sku['product_image']}")
    if payload["subtest"] in {"unit_price", "size_weight"}:
        for sku in skus:
            if float(sku["weight"]) <= 0:
                raise ValueError(f"{payload['scenario_id']} requires parseable positive weight for every SKU.")
    if payload["subtest"] in {"price", "size_weight"}:
        image_paths = {sku["product_image"] for sku in skus}
        base_ids = {str(sku["sku_id"]).rsplit("-P", 1)[0] for sku in skus}
        base_ids = {sku_id.rsplit("-S", 1)[0] for sku_id in base_ids}
        if len(image_paths) != 1 or len(base_ids) != 1:
            raise ValueError(f"{payload['scenario_id']} rationality baseline must use one identical anchor SKU.")


def build_all_payloads(args: argparse.Namespace) -> list[dict[str, Any]]:
    rng = random.Random(args.seed)
    experiments = selected_experiments(args)
    payloads: list[dict[str, Any]] = []
    scenario_set = "full" if args.scenario_set == "all" else args.scenario_set
    configs = [DATASET_BY_SLUG[slug] for slug in args.datasets] if args.datasets else DATASETS
    for config in configs:
        rows = read_rows(config)
        if len(rows) < 8:
            raise ValueError(f"{config.slug} has only {len(rows)} SKU rows with images.")
        for payload in build_payloads(config, rows, scenario_set, rng, price_anchor_index=args.price_anchor_index):
            if payload["subtest"] in experiments:
                payloads.append(normalize_payload(payload))
    return payloads


def group_key(args: argparse.Namespace, payload: dict[str, Any]) -> tuple[str, str]:
    if args.edit_source_scope == "dataset":
        return (dataset_from_scenario_id(payload), payload["subtest"])
    if args.edit_source_scope == "experiment":
        return ("all_datasets", payload["subtest"])
    return ("all_datasets", "all_experiments")


def grouped_payloads(args: argparse.Namespace, payloads: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for payload in payloads:
        groups[group_key(args, payload)].append(payload)
    return dict(groups)


def load_original_payload(args: argparse.Namespace) -> dict[str, Any] | None:
    if not args.original_request_file:
        return None
    payload = json.loads(args.original_request_file.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        if not payload:
            raise ValueError(f"Original request file is empty: {args.original_request_file}")
        return payload[0]
    return payload


def configure_edit_source(payload: dict[str, Any], source: Path, source_payload: dict[str, Any] | None) -> None:
    payload["input_image"] = str(source)
    payload["notes"] = DESIGN_EDIT_NOTES
    if source_payload and source_payload.get("skus"):
        payload["base_skus"] = source_payload["skus"]
    else:
        payload["force_product_references_in_edit"] = True


def write_requests(args: argparse.Namespace, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    if args.allow_missing_product_images:
        raise ValueError("Baseline Setting formal runs require product_image for every SKU; do not use --allow-missing-product-images.")
    if args.send_individual_product_images:
        raise ValueError("Baseline Setting formal runs require --reference-sheet-only behavior; do not use --send-individual-product-images.")
    if not args.original_image:
        raise ValueError("Baseline Setting runs are edit-only. Provide a baseline image with --baseline-image or --original-image.")
    if args.original_image and (not args.original_image.exists() or args.original_image.stat().st_size == 0):
        raise FileNotFoundError(f"Original image is missing or empty: {args.original_image}")
    original_payload = load_original_payload(args)
    groups = grouped_payloads(args, payloads)
    for (group_dataset, group_subtest), items in sorted(groups.items()):
        first_screen: Path | None = None
        previous_screen: Path | None = None
        first_payload: dict[str, Any] | None = original_payload
        previous_payload: dict[str, Any] | None = original_payload
        for order, base_payload in enumerate(items, start=1):
            payload = copy.deepcopy(base_payload)
            mode = "edit"
            dataset = dataset_from_scenario_id(payload)
            subtest = payload["subtest"]
            case_dir = args.output_root / dataset / subtest
            request_file = case_dir / "requests" / f"{order:03d}_{payload['scenario_id']}.json"
            screen_file = case_dir / "screens" / f"{order:03d}_{payload['scenario_id']}.png"
            payload["mode"] = mode
            payload["generation_order"] = order
            payload["edit_source_policy"] = args.edit_source
            payload["edit_source_scope"] = args.edit_source_scope
            source = args.original_image
            source_payload = original_payload
            configure_edit_source(payload, source, source_payload)
            validate_design_payload(payload)
            request_file.parent.mkdir(parents=True, exist_ok=True)
            screen_file.parent.mkdir(parents=True, exist_ok=True)
            request_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            if first_screen is None:
                first_screen = screen_file
                first_payload = copy.deepcopy(payload)
            previous_screen = screen_file
            previous_payload = copy.deepcopy(payload)
            correct_product_number = next(
                index for index, sku in enumerate(payload["skus"], start=1) if sku["sku_id"] == payload["correct_sku_id"]
            )
            manifest.append(
                {
                    "dataset": dataset,
                    "category": payload["category"],
                    "experiment": subtest,
                    "scenario_id": payload["scenario_id"],
                    "item_key": f"{dataset}/{subtest}/{order:03d}_{payload['scenario_id']}",
                    "mode": mode,
                    "generation_order": order,
                    "baseline_family": payload["baseline_family"],
                    "edit_source_policy": args.edit_source,
                    "edit_source_scope": args.edit_source_scope,
                    "group_key": f"{group_dataset}/{group_subtest}",
                    "input_image": payload.get("input_image"),
                    "prompt_instruction": payload["prompt_instruction"],
                    "target_field": payload.get("target_field"),
                    "target_value": payload.get("target_value"),
                    "correct_sku_id": payload["correct_sku_id"],
                    "correct_product_number": correct_product_number,
                    "design_requirements_source": payload["design_requirements_source"],
                    "request_file": str(request_file),
                    "screen_file": str(screen_file),
                }
            )
    args.output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "output_root": str(args.output_root),
                "seed": args.seed,
                "scenario_set": args.scenario_set,
                "price_anchor_index": args.price_anchor_index,
                "experiments": sorted(selected_experiments(args)),
                "edit_source": args.edit_source,
                "edit_source_scope": args.edit_source_scope,
                "original_image": str(args.original_image) if args.original_image else None,
                "original_request_file": str(args.original_request_file) if args.original_request_file else None,
                "design_requirements_source": "generate_image/docs/design.md",
                "reference_sheet_only": True,
                "allow_missing_product_images": False,
                "aspect_ratio": args.aspect_ratio,
                "image_size": args.image_size,
                "count": len(manifest),
                "items": manifest,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest


def command_for(args: argparse.Namespace, item: dict[str, Any]) -> list[str]:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--request-file",
        item["request_file"],
        "--output-file",
        item["screen_file"],
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--aspect-ratio",
        args.aspect_ratio,
        "--image-size",
        args.image_size,
    ]
    if not args.send_individual_product_images:
        cmd.append("--reference-sheet-only")
    if args.allow_missing_product_images:
        cmd.append("--allow-missing-product-images")
    if args.model:
        cmd.extend(["--model", args.model])
    return cmd


TERMINAL_SUCCESS_STATUSES = {"succeeded"}
RETRYABLE_STATUSES = {"failed", "blocked", "missing_source"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def item_key(item: dict[str, Any]) -> str:
    return str(item.get("item_key") or f"{item['dataset']}/{item['experiment']}/{item['generation_order']:03d}_{item['scenario_id']}")


def output_ready(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def default_status_file(args: argparse.Namespace) -> Path:
    return args.status_file or args.output_root / "run_status.json"


def default_events_file(args: argparse.Namespace) -> Path:
    return args.events_file or args.output_root / "run_events.jsonl"


def default_log_dir(args: argparse.Namespace) -> Path:
    return args.log_dir or args.output_root / "logs"


def load_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"items": {}, "summary": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, content: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"time": utc_now(), **event}, ensure_ascii=False) + "\n")


def command_preview(cmd: list[str]) -> str:
    return " ".join(cmd)


def status_counts(status: dict[str, Any], keys: set[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for key in keys:
        item_status = status.get("items", {}).get(key, {}).get("status", "pending")
        counts[str(item_status)] += 1
    return dict(sorted(counts.items()))


def write_checkpoint(
    args: argparse.Namespace,
    status_path: Path,
    status: dict[str, Any],
    selected: list[dict[str, Any]],
    started_at: float,
) -> None:
    keys = {item_key(item) for item in selected}
    status["summary"] = {
        "updated_at": utc_now(),
        "elapsed_seconds": round(time.time() - started_at, 1),
        "total_selected": len(selected),
        "counts": status_counts(status, keys),
    }
    status["run"] = {
        "output_root": str(args.output_root),
        "scenario_set": args.scenario_set,
        "datasets": args.datasets or [config.slug for config in DATASETS],
        "experiments": sorted(selected_experiments(args)),
        "seed": args.seed,
        "edit_source": args.edit_source,
        "edit_source_scope": args.edit_source_scope,
        "original_image": str(args.original_image) if args.original_image else None,
        "original_request_file": str(args.original_request_file) if args.original_request_file else None,
        "aspect_ratio": args.aspect_ratio,
        "image_size": args.image_size,
        "resume": args.resume,
        "retry_failed_only": args.retry_failed_only,
        "keep_going": args.keep_going,
        "requested_workers": args.workers,
        "effective_workers": getattr(args, "effective_workers", args.workers or 1),
        "api_key_env": args.api_key_env,
        "api_key_file": str(args.api_key_file) if args.api_key_file else None,
        "min_delay_per_key_seconds": args.min_delay_per_key_seconds,
        "max_in_flight_per_key": args.max_in_flight_per_key,
    }
    atomic_write_json(status_path, status)


def update_item_status(
    status: dict[str, Any],
    item: dict[str, Any],
    state: str,
    **fields: Any,
) -> None:
    key = item_key(item)
    current = status.setdefault("items", {}).get(key, {})
    current.update(
        {
            "status": state,
            "updated_at": utc_now(),
            "item_key": key,
            "dataset": item["dataset"],
            "experiment": item["experiment"],
            "scenario_id": item["scenario_id"],
            "mode": item["mode"],
            "generation_order": item["generation_order"],
            "request_file": item["request_file"],
            "screen_file": item["screen_file"],
        }
    )
    current.update(fields)
    status["items"][key] = current


def progress_line(index: int, total: int, item: dict[str, Any], state: str, status: dict[str, Any], selected: list[dict[str, Any]], started_at: float) -> str:
    counts = status_counts(status, {item_key(entry) for entry in selected})
    elapsed = time.time() - started_at
    done = sum(counts.get(name, 0) for name in ("succeeded", "failed", "blocked"))
    rate = done / elapsed if elapsed > 0 else 0
    remaining = total - done
    eta = int(remaining / rate) if rate > 0 else None
    eta_text = f", eta={eta}s" if eta is not None else ""
    return (
        f"[{index}/{total}] {state} {item['mode']} {item['scenario_id']} | "
        f"counts={counts}, elapsed={int(elapsed)}s{eta_text}"
    )


def should_select_for_retry(item: dict[str, Any], status: dict[str, Any]) -> bool:
    output = Path(item["screen_file"])
    if not output_ready(output):
        return True
    state = status.get("items", {}).get(item_key(item), {}).get("status")
    return state in RETRYABLE_STATUSES


def redact_sensitive_text(text: str | None, sensitive_values: list[str] | None) -> str | None:
    if not text:
        return text
    redacted = text
    for value in sensitive_values or []:
        if value and len(value) >= 8:
            redacted = redacted.replace(value, "[REDACTED_OPENROUTER_API_KEY]")
    return redacted


def write_attempt_log(
    log_dir: Path,
    item: dict[str, Any],
    attempt: int,
    stdout: str | None,
    stderr: str | None,
    redact_values: list[str] | None = None,
) -> Path | None:
    stdout_text = stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else stdout
    stderr_text = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr
    stdout_text = redact_sensitive_text(stdout_text, redact_values)
    stderr_text = redact_sensitive_text(stderr_text, redact_values)
    if not stdout_text and not stderr_text:
        return None
    safe_key = item_key(item).replace("/", "__").replace(" ", "_")
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{safe_key}_attempt{attempt}.log"
    path.write_text(
        "\n".join(
            [
                f"time={utc_now()}",
                f"item_key={item_key(item)}",
                f"attempt={attempt}",
                "",
                "STDOUT:",
                stdout_text or "",
                "",
                "STDERR:",
                stderr_text or "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def load_api_keys(args: argparse.Namespace) -> list[str]:
    values: list[str] = []
    if args.api_key_file:
        values.extend(
            line.strip()
            for line in args.api_key_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    env_value = os.getenv(args.api_key_env, "")
    if env_value:
        values.extend(part.strip() for part in env_value.replace("\n", ",").split(",") if part.strip())
    fallback = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not values and fallback:
        values.append(fallback)

    deduped = []
    seen = set()
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def effective_worker_count(args: argparse.Namespace, api_keys: list[str]) -> int:
    if args.workers is not None:
        return args.workers
    return max(1, len(api_keys))


class ApiKeyPool:
    def __init__(self, api_keys: list[str], max_in_flight_per_key: int, min_delay_seconds: float) -> None:
        self.api_keys = api_keys
        self.max_in_flight_per_key = max(1, max_in_flight_per_key)
        self.min_delay_seconds = max(0.0, min_delay_seconds)
        self.condition = threading.Condition()
        self.in_flight = [0 for _ in api_keys]
        self.last_start = [0.0 for _ in api_keys]
        self.next_index = 0

    def acquire(self) -> tuple[int | None, str | None]:
        if not self.api_keys:
            return None, None
        with self.condition:
            while True:
                now = time.monotonic()
                key_count = len(self.api_keys)
                for offset in range(key_count):
                    index = (self.next_index + offset) % key_count
                    delay_remaining = self.min_delay_seconds - (now - self.last_start[index])
                    if self.in_flight[index] < self.max_in_flight_per_key and delay_remaining <= 0:
                        self.in_flight[index] += 1
                        self.last_start[index] = now
                        self.next_index = (index + 1) % key_count
                        return index, self.api_keys[index]
                waits = [
                    max(0.0, self.min_delay_seconds - (now - self.last_start[index]))
                    for index in range(key_count)
                    if self.in_flight[index] < self.max_in_flight_per_key
                ]
                self.condition.wait(timeout=min(waits) if waits else 0.5)

    def release(self, index: int | None) -> None:
        if index is None:
            return
        with self.condition:
            self.in_flight[index] = max(0, self.in_flight[index] - 1)
            self.condition.notify_all()


def subprocess_env_for_key(api_key: str | None) -> dict[str, str] | None:
    if not api_key:
        return None
    env = os.environ.copy()
    env["OPENROUTER_API_KEY"] = api_key
    return env


def dependency_key_for_item(item: dict[str, Any], output_to_key: dict[str, str]) -> str | None:
    input_image = item.get("input_image")
    if not input_image:
        return None
    return output_to_key.get(str(Path(input_image)))


def external_edit_source_missing(item: dict[str, Any], output_to_key: dict[str, str]) -> bool:
    input_image = item.get("input_image")
    if not input_image:
        return False
    path = Path(input_image)
    if str(path) in output_to_key:
        return False
    return not output_ready(path)


def mark_blocked(
    args: argparse.Namespace,
    status: dict[str, Any],
    status_path: Path,
    events_path: Path,
    item: dict[str, Any],
    selected: list[dict[str, Any]],
    started_at: float,
    lock: threading.Lock,
    reason: str,
    error: str,
) -> dict[str, Any]:
    with lock:
        update_item_status(status, item, "blocked", reason=reason, error=error)
        append_event(events_path, {"event": "blocked", "item_key": item_key(item), "reason": reason, "error": error})
        write_checkpoint(args, status_path, status, selected, started_at)
    return {"item_key": item_key(item), "status": "blocked", "error": error}


def generate_item_worker(
    args: argparse.Namespace,
    item: dict[str, Any],
    index: int,
    total: int,
    status: dict[str, Any],
    status_path: Path,
    events_path: Path,
    log_dir: Path,
    selected: list[dict[str, Any]],
    started_at: float,
    lock: threading.Lock,
    key_pool: ApiKeyPool,
) -> dict[str, Any]:
    output = Path(item["screen_file"])
    key = item_key(item)
    cmd = command_for(args, item)
    with lock:
        update_item_status(status, item, "running", attempts_started=0, command=command_preview(cmd))
        write_checkpoint(args, status_path, status, selected, started_at)

    for attempt in range(1, args.attempts + 1):
        attempt_started_at = time.time()
        key_index, api_key = key_pool.acquire()
        try:
            with lock:
                update_item_status(
                    status,
                    item,
                    "running",
                    attempts_started=attempt,
                    command=command_preview(cmd),
                    api_key_index=key_index,
                )
                append_event(
                    events_path,
                    {
                        "event": "attempt_started",
                        "item_key": key,
                        "attempt": attempt,
                        "attempts": args.attempts,
                        "api_key_index": key_index,
                        "command": command_preview(cmd),
                    },
                )
                write_checkpoint(args, status_path, status, selected, started_at)
            print(f"[{index}/{total}] {item['mode']} {item['scenario_id']} attempt {attempt}/{args.attempts}", flush=True)

            result = subprocess.run(
                cmd,
                check=False,
                timeout=args.subprocess_timeout_seconds,
                text=True,
                capture_output=True,
                env=subprocess_env_for_key(api_key),
            )
            log_path = write_attempt_log(log_dir, item, attempt, result.stdout, result.stderr, redact_values=[api_key] if api_key else None)
            if result.returncode != 0:
                raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
            if not output_ready(output):
                raise RuntimeError(f"Command succeeded but output image is missing or empty: {output}")
            elapsed = round(time.time() - attempt_started_at, 1)
            with lock:
                update_item_status(
                    status,
                    item,
                    "succeeded",
                    attempts_completed=attempt,
                    elapsed_seconds=elapsed,
                    output_bytes=output.stat().st_size,
                    log_file=str(log_path) if log_path else None,
                    api_key_index=key_index,
                )
                append_event(
                    events_path,
                    {
                        "event": "attempt_succeeded",
                        "item_key": key,
                        "attempt": attempt,
                        "elapsed_seconds": elapsed,
                        "screen_file": str(output),
                        "output_bytes": output.stat().st_size,
                        "log_file": str(log_path) if log_path else None,
                        "api_key_index": key_index,
                    },
                )
                write_checkpoint(args, status_path, status, selected, started_at)
                line = progress_line(index, total, item, "succeeded", status, selected, started_at)
            print(line, flush=True)
            return {"item_key": key, "status": "succeeded"}
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            stdout = getattr(exc, "stdout", None) or getattr(exc, "output", None)
            stderr = getattr(exc, "stderr", None)
            log_path = write_attempt_log(log_dir, item, attempt, stdout, stderr, redact_values=[api_key] if api_key else None)
            error = str(exc)
            with lock:
                append_event(
                    events_path,
                    {
                        "event": "attempt_failed",
                        "item_key": key,
                        "attempt": attempt,
                        "error": error,
                        "log_file": str(log_path) if log_path else None,
                        "api_key_index": key_index,
                    },
                )
            if attempt >= args.attempts:
                with lock:
                    update_item_status(
                        status,
                        item,
                        "failed",
                        attempts_completed=attempt,
                        error=error,
                        log_file=str(log_path) if log_path else None,
                        api_key_index=key_index,
                    )
                    write_checkpoint(args, status_path, status, selected, started_at)
                    line = progress_line(index, total, item, "failed", status, selected, started_at)
                print(line, flush=True)
                return {"item_key": key, "status": "failed", "error": error}
            print(f"Retrying in {args.retry_delay_seconds}s after: {exc}", flush=True)
            time.sleep(args.retry_delay_seconds)
        except Exception as exc:
            error = str(exc)
            with lock:
                append_event(
                    events_path,
                    {
                        "event": "attempt_failed",
                        "item_key": key,
                        "attempt": attempt,
                        "error": error,
                        "api_key_index": key_index,
                    },
                )
            if attempt >= args.attempts:
                with lock:
                    update_item_status(status, item, "failed", attempts_completed=attempt, error=error, api_key_index=key_index)
                    write_checkpoint(args, status_path, status, selected, started_at)
                    line = progress_line(index, total, item, "failed", status, selected, started_at)
                print(line, flush=True)
                return {"item_key": key, "status": "failed", "error": error}
            print(f"Retrying in {args.retry_delay_seconds}s after: {exc}", flush=True)
            time.sleep(args.retry_delay_seconds)
        finally:
            key_pool.release(key_index)

    return {"item_key": key, "status": "failed", "error": "exhausted attempts"}


def run_generation_concurrent(
    args: argparse.Namespace,
    selected: list[dict[str, Any]],
    status: dict[str, Any],
    status_path: Path,
    events_path: Path,
    log_dir: Path,
    started_at: float,
    api_keys: list[str],
) -> list[dict[str, Any]]:
    effective_workers = effective_worker_count(args, api_keys)
    key_pool = ApiKeyPool(
        api_keys=api_keys,
        max_in_flight_per_key=args.max_in_flight_per_key,
        min_delay_seconds=args.min_delay_per_key_seconds,
    )
    output_to_key = {str(Path(item["screen_file"])): item_key(item) for item in selected}
    pending = {item_key(item): item for item in selected}
    completed_success: set[str] = set()
    completed_failure: set[str] = set()
    failures: list[dict[str, Any]] = []
    lock = threading.Lock()

    for index, item in enumerate(selected, start=1):
        output = Path(item["screen_file"])
        key = item_key(item)
        previous = status.get("items", {}).get(key, {})
        if args.resume and previous.get("status") in TERMINAL_SUCCESS_STATUSES and output_ready(output):
            with lock:
                update_item_status(status, item, "succeeded", reason="resume_completed", output_bytes=output.stat().st_size)
                append_event(events_path, {"event": "skipped_completed", "item_key": key, "screen_file": str(output)})
                write_checkpoint(args, status_path, status, selected, started_at)
                line = progress_line(index, len(selected), item, "resume-skip", status, selected, started_at)
            print(line, flush=True)
            completed_success.add(key)
            pending.pop(key, None)
        elif args.skip_existing and output_ready(output):
            with lock:
                update_item_status(status, item, "succeeded", reason="skip_existing", output_bytes=output.stat().st_size)
                append_event(events_path, {"event": "skipped_existing", "item_key": key, "screen_file": str(output)})
                write_checkpoint(args, status_path, status, selected, started_at)
                line = progress_line(index, len(selected), item, "skip-existing", status, selected, started_at)
            print(line, flush=True)
            completed_success.add(key)
            pending.pop(key, None)

    index_by_key = {item_key(item): index for index, item in enumerate(selected, start=1)}
    in_flight: dict[Future[dict[str, Any]], str] = {}
    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        while pending or in_flight:
            launched = False
            for key, item in list(pending.items()):
                dependency = dependency_key_for_item(item, output_to_key)
                if dependency and dependency in completed_failure:
                    error = f"Dependency failed or was blocked: {dependency}"
                    result = mark_blocked(
                        args,
                        status,
                        status_path,
                        events_path,
                        item,
                        selected,
                        started_at,
                        lock,
                        reason="dependency_failed",
                        error=error,
                    )
                    failures.append(result)
                    completed_failure.add(key)
                    pending.pop(key, None)
                    if not args.keep_going:
                        raise RuntimeError(error)
                    continue
                if dependency and dependency not in completed_success:
                    continue
                if external_edit_source_missing(item, output_to_key):
                    error = f"External edit source image is missing or empty: {item.get('input_image')}"
                    result = mark_blocked(
                        args,
                        status,
                        status_path,
                        events_path,
                        item,
                        selected,
                        started_at,
                        lock,
                        reason="missing_external_edit_source",
                        error=error,
                    )
                    failures.append(result)
                    completed_failure.add(key)
                    pending.pop(key, None)
                    if not args.keep_going:
                        raise FileNotFoundError(error)
                    continue
                if len(in_flight) >= effective_workers:
                    break
                future = executor.submit(
                    generate_item_worker,
                    args,
                    item,
                    index_by_key[key],
                    len(selected),
                    status,
                    status_path,
                    events_path,
                    log_dir,
                    selected,
                    started_at,
                    lock,
                    key_pool,
                )
                in_flight[future] = key
                pending.pop(key, None)
                launched = True

            if not in_flight:
                for key, item in list(pending.items()):
                    error = "No runnable dependency path remains for this item."
                    result = mark_blocked(
                        args,
                        status,
                        status_path,
                        events_path,
                        item,
                        selected,
                        started_at,
                        lock,
                        reason="unresolved_dependency",
                        error=error,
                    )
                    failures.append(result)
                    completed_failure.add(key)
                    pending.pop(key, None)
                break

            if not launched or len(in_flight) >= effective_workers:
                done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                for future in done:
                    key = in_flight.pop(future)
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {"item_key": key, "status": "failed", "error": str(exc)}
                    if result.get("status") == "succeeded":
                        completed_success.add(key)
                    else:
                        completed_failure.add(key)
                        failures.append(result)
                        if not args.keep_going:
                            raise RuntimeError(result.get("error", f"Image generation failed for {key}"))
    return failures


def run_generation(args: argparse.Namespace, manifest: list[dict[str, Any]]) -> None:
    started_at = time.time()
    status_path = default_status_file(args)
    events_path = default_events_file(args)
    log_dir = default_log_dir(args)
    status = load_status(status_path) if args.resume else {"items": {}, "summary": {}}
    selected = manifest[: args.limit] if args.limit else manifest
    if args.retry_failed_only:
        selected = [item for item in selected if should_select_for_retry(item, status)]
    api_keys = load_api_keys(args)
    if args.workers is not None and args.workers < 1:
        raise ValueError("--workers must be >= 1.")
    args.effective_workers = effective_worker_count(args, api_keys)
    write_checkpoint(args, status_path, status, selected, started_at)
    append_event(
        events_path,
        {
            "event": "run_started",
            "status_file": str(status_path),
            "total_selected": len(selected),
            "retry_failed_only": args.retry_failed_only,
            "resume": args.resume,
            "workers": args.effective_workers,
            "api_key_count": len(api_keys),
        },
    )

    if api_keys or args.effective_workers > 1:
        failures = run_generation_concurrent(
            args=args,
            selected=selected,
            status=status,
            status_path=status_path,
            events_path=events_path,
            log_dir=log_dir,
            started_at=started_at,
            api_keys=api_keys,
        )
        write_checkpoint(args, status_path, status, selected, started_at)
        append_event(
            events_path,
            {
                "event": "run_finished",
                "status_file": str(status_path),
                "failures": len(failures),
                "summary": status.get("summary", {}),
            },
        )
        if failures:
            failure_path = args.output_root / "failed_items.json"
            atomic_write_json(failure_path, {"count": len(failures), "items": failures})
            print(f"Finished with {len(failures)} failed/blocked items. See {failure_path}", flush=True)
        return

    failures: list[dict[str, Any]] = []
    for index, item in enumerate(selected, start=1):
        output = Path(item["screen_file"])
        key = item_key(item)
        previous = status.get("items", {}).get(key, {})
        if args.resume and previous.get("status") in TERMINAL_SUCCESS_STATUSES and output_ready(output):
            update_item_status(status, item, "succeeded", reason="resume_completed", output_bytes=output.stat().st_size)
            append_event(events_path, {"event": "skipped_completed", "item_key": key, "screen_file": str(output)})
            write_checkpoint(args, status_path, status, selected, started_at)
            print(progress_line(index, len(selected), item, "resume-skip", status, selected, started_at), flush=True)
            continue
        if args.skip_existing and output.exists() and output.stat().st_size > 0:
            update_item_status(status, item, "succeeded", reason="skip_existing", output_bytes=output.stat().st_size)
            append_event(events_path, {"event": "skipped_existing", "item_key": key, "screen_file": str(output)})
            write_checkpoint(args, status_path, status, selected, started_at)
            print(progress_line(index, len(selected), item, "skip-existing", status, selected, started_at), flush=True)
            continue
        if item["mode"] == "edit":
            source = Path(item["input_image"])
            if not source.exists() or source.stat().st_size == 0:
                message = (
                    f"Edit source image is missing for {item['scenario_id']}: {source}. "
                    "Provide a valid baseline image with --baseline-image or --original-image."
                )
                update_item_status(status, item, "blocked", reason="missing_edit_source", error=message)
                append_event(events_path, {"event": "blocked", "item_key": key, "error": message})
                write_checkpoint(args, status_path, status, selected, started_at)
                failures.append({"item_key": key, "status": "blocked", "error": message})
                print(progress_line(index, len(selected), item, "blocked", status, selected, started_at), flush=True)
                if not args.keep_going:
                    raise FileNotFoundError(message)
                continue
        cmd = command_for(args, item)
        update_item_status(status, item, "running", attempts_started=0, command=command_preview(cmd))
        write_checkpoint(args, status_path, status, selected, started_at)
        for attempt in range(1, args.attempts + 1):
            attempt_started_at = time.time()
            update_item_status(status, item, "running", attempts_started=attempt, command=command_preview(cmd))
            append_event(
                events_path,
                {
                    "event": "attempt_started",
                    "item_key": key,
                    "attempt": attempt,
                    "attempts": args.attempts,
                    "command": command_preview(cmd),
                },
            )
            write_checkpoint(args, status_path, status, selected, started_at)
            print(f"[{index}/{len(selected)}] {item['mode']} {item['scenario_id']} attempt {attempt}/{args.attempts}", flush=True)
            try:
                result = subprocess.run(
                    cmd,
                    check=False,
                    timeout=args.subprocess_timeout_seconds,
                    text=True,
                    capture_output=True,
                )
                log_path = write_attempt_log(log_dir, item, attempt, result.stdout, result.stderr)
                if result.returncode != 0:
                    raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
                if not output_ready(output):
                    raise RuntimeError(f"Command succeeded but output image is missing or empty: {output}")
                elapsed = round(time.time() - attempt_started_at, 1)
                update_item_status(
                    status,
                    item,
                    "succeeded",
                    attempts_completed=attempt,
                    elapsed_seconds=elapsed,
                    output_bytes=output.stat().st_size,
                    log_file=str(log_path) if log_path else None,
                )
                append_event(
                    events_path,
                    {
                        "event": "attempt_succeeded",
                        "item_key": key,
                        "attempt": attempt,
                        "elapsed_seconds": elapsed,
                        "screen_file": str(output),
                        "output_bytes": output.stat().st_size,
                        "log_file": str(log_path) if log_path else None,
                    },
                )
                write_checkpoint(args, status_path, status, selected, started_at)
                print(progress_line(index, len(selected), item, "succeeded", status, selected, started_at), flush=True)
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                stdout = getattr(exc, "stdout", None) or getattr(exc, "output", None)
                stderr = getattr(exc, "stderr", None)
                log_path = write_attempt_log(log_dir, item, attempt, stdout, stderr)
                error = str(exc)
                append_event(
                    events_path,
                    {
                        "event": "attempt_failed",
                        "item_key": key,
                        "attempt": attempt,
                        "error": error,
                        "log_file": str(log_path) if log_path else None,
                    },
                )
                if attempt >= args.attempts:
                    update_item_status(status, item, "failed", attempts_completed=attempt, error=error, log_file=str(log_path) if log_path else None)
                    write_checkpoint(args, status_path, status, selected, started_at)
                    failures.append({"item_key": key, "status": "failed", "error": error})
                    print(progress_line(index, len(selected), item, "failed", status, selected, started_at), flush=True)
                    if not args.keep_going:
                        raise RuntimeError(f"Image generation failed for {item['scenario_id']}") from exc
                    break
                print(f"Retrying in {args.retry_delay_seconds}s after: {exc}", flush=True)
                time.sleep(args.retry_delay_seconds)
            except Exception as exc:
                error = str(exc)
                append_event(events_path, {"event": "attempt_failed", "item_key": key, "attempt": attempt, "error": error})
                if attempt >= args.attempts:
                    update_item_status(status, item, "failed", attempts_completed=attempt, error=error)
                    write_checkpoint(args, status_path, status, selected, started_at)
                    failures.append({"item_key": key, "status": "failed", "error": error})
                    print(progress_line(index, len(selected), item, "failed", status, selected, started_at), flush=True)
                    if not args.keep_going:
                        raise RuntimeError(f"Image generation failed for {item['scenario_id']}") from exc
                    break
                print(f"Retrying in {args.retry_delay_seconds}s after: {exc}", flush=True)
                time.sleep(args.retry_delay_seconds)

    write_checkpoint(args, status_path, status, selected, started_at)
    append_event(
        events_path,
        {
            "event": "run_finished",
            "status_file": str(status_path),
            "failures": len(failures),
            "summary": status.get("summary", {}),
        },
    )
    if failures:
        failure_path = args.output_root / "failed_items.json"
        atomic_write_json(failure_path, {"count": len(failures), "items": failures})
        print(f"Finished with {len(failures)} failed/blocked items. See {failure_path}", flush=True)


def main() -> None:
    args = parse_args()
    payloads = build_all_payloads(args)
    manifest = write_requests(args, payloads)
    print(
        json.dumps(
            {
                "output_root": str(args.output_root),
                "requests": len(manifest),
                "manifest": str(args.output_root / "manifest.json"),
                "generate": args.generate,
                "status_file": str(default_status_file(args)) if args.generate else None,
                "events_file": str(default_events_file(args)) if args.generate else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.generate:
        run_generation(args, manifest)


if __name__ == "__main__":
    main()
