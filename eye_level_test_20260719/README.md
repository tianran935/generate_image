# Eye-level shelf image test

This directory contains a small controlled image-generation test for whether an
explicit shopper eye-level cue changes a downstream LLM's visual choice.

The test keeps the same eight TORTILLA CHIPS SKUs, product images, prices,
promotions, badges, positions, and sizes across two generated stimulus images.
Only the eye-level instruction changes:

- `row1_eye_level`: row 1 is described as the shopper's eye-level row.
- `row2_eye_level`: row 2 is described as the shopper's eye-level row.

Run from the repository root:

```bash
python generate_image/eye_level_test_20260719/run_eye_level_test.py
```

Outputs are written to `output/` inside this directory.
