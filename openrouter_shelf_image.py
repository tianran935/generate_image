from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from typing import Any

import requests

from shelf_sampling import (
    DEFAULT_CATALOG_FILE,
    build_edit_payload,
    build_generate_payload,
    parse_categories,
    sample_products,
)


API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-5.4-image-2"


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
    parser.add_argument("--request-output-file", type=Path, help="Optional JSON file to save built request payloads.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter image model.")
    parser.add_argument("--aspect-ratio", default="4:3", help="Image aspect ratio.")
    parser.add_argument("--image-size", default="1K", choices=["1K", "2K"], help="Image size.")
    parser.add_argument("--timeout-seconds", type=int, default=360, help="HTTP timeout in seconds.")
    return parser.parse_args()


def load_request(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def encode_local_image(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/png"
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif suffix == ".webp":
        mime = "image/webp"
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


def format_sku_lines(items: list[dict[str, Any]]) -> str:
    lines = []
    for item in items:
        promo = item.get("promotion", "none")
        price = item.get("price", "unknown")
        size = item.get("size", "unknown")
        tags = ", ".join(item.get("tags", [])) or promo
        source = item.get("source_row", {})
        rank = source.get("rank_within_category", "unknown") if isinstance(source, dict) else "unknown"
        lines.append(
            f'- {item["sku_id"]}: item="{item["item"]}", size="{size}", price="{price}", tags="{tags}", '
            f'promotion="{promo}", category="{item.get("category_name", "unknown")}", source_rank="{rank}", '
            f'position=(row {item["position"]["row"]}, col {item["position"]["col"]})'
        )
    return "\n".join(lines)


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
        "Use a strict 2 by 4 layout: two horizontal shelf rows and four product columns, for exactly eight focal products. "
        "Render a realistic grocery shelf photograph that matches a real supermarket shelf. "
        "The shelf should be densely stocked and visually full, with products filling almost all visible facing space. "
        "Avoid large empty gaps or obviously sparse experimental layouts unless a gap is explicitly requested. "
        "Use repeated facings and neighboring filler products from the same category when needed so the shelf looks naturally merchandised. "
        "Keep the requested target SKUs at their specified positions and preserve their item identity, price cue, and promotion type. "
        "Make price tags and promotion markers visible and believable. "
        "The final image should look like a real fully merchandised cereal shelf in a supermarket rather than a minimal mockup."
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
        "Do not change product identities, shelf framing, background, lighting, camera angle, or visual style. "
        "Only change the requested attributes: product positions, Sponsored tags, Overall Pick tag, Only X Remaining tag, prices, and sizes. "
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
        return [build_edit_payload(args.input_image, payload, seed=args.seed) for payload in base_payloads]
    samples = sample_products(
        categories=parse_categories(args.categories),
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
    return [build_edit_payload(args.input_image, payload, seed=args.seed) for payload in payloads]


def resolve_output_file(args: argparse.Namespace, payload: dict[str, Any], index: int, total: int) -> Path:
    if args.output_file and total == 1:
        return args.output_file
    output_dir = args.output_dir or (args.output_file.parent if args.output_file else Path("output"))
    category = str(payload.get("category", "shelf")).lower().replace(" ", "_").replace("/", "_")
    mode = payload["mode"]
    sample_index = payload.get("sample_index", index)
    return output_dir / f"{mode}_{category}_sample_{sample_index}.png"


def save_request_payloads(path: Path, payloads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content: Any = payloads[0] if len(payloads) == 1 else payloads
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


def build_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    mode = payload["mode"]
    if mode == "generate":
        return [{"role": "user", "content": build_generate_prompt(payload)}]

    if mode == "edit":
        input_image_path = Path(payload["input_image"])
        if not input_image_path.exists():
            raise FileNotFoundError(f"Input image not found for edit mode: {input_image_path}")
        return [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": build_edit_prompt(payload)},
                    {"type": "image_url", "image_url": {"url": encode_local_image(input_image_path)}},
                ],
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
        raise ValueError("No generated image found in OpenRouter response.")
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

    if args.request_output_file:
        save_request_payloads(args.request_output_file, payloads)

    if not args.output_file and not args.output_dir:
        raise ValueError("--output-file or --output-dir is required.")

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")

    outputs = []
    for index, payload in enumerate(payloads):
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
        output_file = resolve_output_file(args, payload, index, len(payloads))
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(image_bytes)
        outputs.append(str(output_file))

    print(
        json.dumps(
            {
                "model": args.model,
                "outputs": outputs,
                "request_file": str(args.request_file) if args.request_file else None,
                "request_output_file": str(args.request_output_file) if args.request_output_file else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
