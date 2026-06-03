from __future__ import annotations

import argparse
import json
from pathlib import Path

from shelf_sampling import (
    DEFAULT_CATALOG_FILE,
    build_edit_payload,
    build_generate_payload,
    parse_categories,
    sample_products,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an edit-mode shelf request with randomized attributes.")
    parser.add_argument("--input-image", type=Path, required=True, help="Original shelf image to edit.")
    parser.add_argument("--output-file", type=Path, required=True, help="Output edit request JSON.")
    parser.add_argument("--base-request-file", type=Path, help="Generate request JSON to preserve SKU identities.")
    parser.add_argument("--catalog-file", type=Path, default=DEFAULT_CATALOG_FILE)
    parser.add_argument("--category", "--categories", dest="categories", action="append")
    parser.add_argument("--sample-size", type=int, default=8)
    parser.add_argument("--sample-count", type=int, default=1)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--sponsored-count", type=int, choices=[1, 2, 3, 4])
    parser.add_argument("--scarcity-remaining", type=int, choices=[1, 2, 3, 4, 5])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.base_request_file:
        base_payload = json.loads(args.base_request_file.read_text(encoding="utf-8"))
        base_payloads = base_payload if isinstance(base_payload, list) else [base_payload]
        payloads = [
            build_edit_payload(
                input_image=args.input_image,
                base_payload=payload,
                seed=args.seed,
                sponsored_count=args.sponsored_count,
                scarcity_remaining=args.scarcity_remaining,
            )
            for payload in base_payloads
        ]
    else:
        samples = sample_products(
            categories=parse_categories(args.categories),
            sample_size=args.sample_size,
            sample_count=args.sample_count,
            catalog_file=args.catalog_file,
            seed=args.seed,
        )
        payloads = [
            build_edit_payload(
                input_image=args.input_image,
                base_payload=build_generate_payload(sample, seed=args.seed),
                seed=args.seed,
                sponsored_count=args.sponsored_count,
                scarcity_remaining=args.scarcity_remaining,
            )
            for sample in samples
        ]

    content = payloads[0] if len(payloads) == 1 else payloads
    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output_file": str(args.output_file), "count": len(payloads)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
