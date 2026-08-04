# generate_image

该目录是本项目的货架图片生成工作区，面向大量 LLM 生成/改图实验。推荐从仓库根目录运行命令，根目录下的旧入口文件仍然保留为兼容包装；真正实现已经分到 `core/`、`experiments/`、`checks/` 和 `docs/`。

## 目录结构

```text
generate_image/
  README.md                         # 本入口索引
  core/                             # 通用生成、改图、采样、请求构造实现
    openrouter_shelf_image.py       # 主实现：OpenRouter 调用、prompt、参考图 sheet
    shelf_sampling.py               # 从 CSV 抽样并构造 2x4 payload
    build_edit_request.py           # 从原图/base request 构造 edit request
  experiments/                      # 批量实验请求和生成调度
    build_min_capability_requests.py
    run_baseline_setting_images.py
  checks/                           # 真实 OpenRouter 集成检查
    test_generate_image_mode.py
    test_price_only_edit_mode.py
  docs/                             # 实验设计与参数说明
  eye_level_test_20260719/          # eye-level 专项实验
  output/                           # 运行产物和最终数据集，已被 .gitignore 忽略
```

兼容入口仍可直接调用：

- `generate_image/openrouter_shelf_image.py`
- `generate_image/shelf_sampling.py`
- `generate_image/build_edit_request.py`
- `generate_image/build_min_capability_requests.py`
- `generate_image/run_baseline_setting_images.py`
- `generate_image/test_generate_image_mode.py`
- `generate_image/test_price_only_edit_mode.py`

## 环境

真实生图/改图需要设置：

```bash
export OPENROUTER_API_KEY="..."
```

大批量并发可以提供多个 key：

```bash
export OPENROUTER_API_KEYS="key1,key2,key3"
```

也可以使用一行一个 key 的文件，并在运行时传 `--api-key-file path/to/openrouter_keys.txt`。如果没有提供多 key 环境变量或 key 文件，脚本才会回退使用单个 `OPENROUTER_API_KEY`。状态文件和事件日志只记录 `api_key_index`，不记录 key 原文；子进程 stdout/stderr 日志也会对当前使用的 key 做脱敏。

默认模型：

```text
openai/gpt-5.4-image-2
```

默认商品参考图目录现在是：

```text
pic_reference/
```

该目录会递归查找 `jpg/jpeg/png/webp/gif`，并按 UPC 或 `rankXX` 匹配商品图。

## 核心入口

只抽样，不调用 OpenRouter：

```bash
python generate_image/shelf_sampling.py \
  --category "TORTILLA CHIPS" \
  --sample-size 8 \
  --sample-count 1 \
  --payload-mode generate \
  --output-file generate_image/output/sample_generate_payload.json
```

注意：`--payload-mode generate` 使用固定 2x4 货架，`--sample-size` 应为 `8`。

从 CSV 抽样并直接生图：

```bash
python generate_image/openrouter_shelf_image.py \
  --mode generate \
  --category "TORTILLA CHIPS" \
  --sample-size 8 \
  --sample-count 1 \
  --seed 42 \
  --reference-sheet-only \
  --request-output-file generate_image/output/generate_request.json \
  --output-file generate_image/output/shelf.png
```

从已有 request 生图：

```bash
python generate_image/openrouter_shelf_image.py \
  --request-file generate_image/output/generate_request.json \
  --reference-sheet-only \
  --output-file generate_image/output/shelf.png
```

构造 edit request，不调用 OpenRouter：

```bash
python generate_image/build_edit_request.py \
  --input-image generate_image/output/shelf.png \
  --base-request-file generate_image/output/generate_request.json \
  --promotion-count 0 \
  --bestseller-count 1 \
  --seed 43 \
  --output-file generate_image/output/edit_request.json
```

执行 edit request：

```bash
python generate_image/openrouter_shelf_image.py \
  --request-file generate_image/output/edit_request.json \
  --reference-sheet-only \
  --output-file generate_image/output/shelf_edit.png
```

## 批量实验入口

构造 minimum-capability 请求，不生图：

```bash
python generate_image/build_min_capability_requests.py \
  --scenario-set core \
  --datasets tortilla_chips \
  --output-root generate_image/output/min_capability_core
```

构造并批量生图：

```bash
python generate_image/build_min_capability_requests.py \
  --scenario-set full \
  --datasets tortilla_chips cold_cereal coffee \
  --output-root generate_image/output/min_capability_full \
  --generate \
  --limit 20 \
  --skip-existing
```

Baseline Setting 正式实验请求，不生图：

```bash
python generate_image/run_baseline_setting_images.py \
  --scenario-set core \
  --datasets tortilla_chips \
  --experiments budget brand flavor size price size_weight \
  --baseline-image path/to/baseline.png \
  --output-root generate_image/output/baseline_setting
```

Baseline Setting 批量生图：

```bash
python generate_image/run_baseline_setting_images.py \
  --scenario-set full \
  --datasets tortilla_chips cold_cereal coffee at_home_crackers carbonated_soft_drinks \
  --experiments budget brand flavor size price size_weight \
  --baseline-image path/to/baseline.png \
  --output-root generate_image/output/baseline_setting \
  --generate \
  --limit 20 \
  --skip-existing
```

Baseline Setting 现在是 edit-only：必须提供一张基准货架图，所有 request 都写为 `mode=edit`，不会自动生成第一张原始图。推荐使用 `--baseline-image`；`--original-image` 仍作为兼容别名。

```bash
python generate_image/run_baseline_setting_images.py \
  --baseline-image path/to/baseline.png \
  --original-request-file path/to/original_request.json \
  --generate \
  ...
```

`--original-request-file` 可选；提供后会用其中的 `skus` 构造差分提示词，不提供则强制随 edit request 传商品参考图。

Baseline Setting 大批量续跑：

```bash
python generate_image/run_baseline_setting_images.py \
  --scenario-set full \
  --datasets tortilla_chips cold_cereal coffee at_home_crackers carbonated_soft_drinks \
  --experiments budget brand flavor size price size_weight \
  --baseline-image path/to/baseline.png \
  --output-root generate_image/output/runs/baseline_setting/full_YYYYMMDD \
  --generate \
  --resume \
  --skip-existing \
  --keep-going
```

续跑与进度文件：

- `run_status.json`：断点状态，记录每个样本的 `pending/running/succeeded/failed/blocked`。
- `run_events.jsonl`：逐事件日志，记录 run start、attempt start、attempt fail/success、run finish。
- `logs/*.log`：每次子进程调用的 stdout/stderr，方便排查失败原因。
- `failed_items.json`：本轮失败或 blocked 的样本清单。

只重试失败/缺失项：

```bash
python generate_image/run_baseline_setting_images.py \
  --output-root generate_image/output/runs/baseline_setting/full_YYYYMMDD \
  --generate \
  --retry-failed-only \
  --resume
```

默认会 `--resume`、`--skip-existing`、`--keep-going`；如果希望第一个失败就停止，用 `--fail-fast`。

Baseline Setting 多 key 并发与限流：

```bash
export OPENROUTER_API_KEYS="key1,key2,key3"

python generate_image/run_baseline_setting_images.py \
  --scenario-set full \
  --datasets tortilla_chips cold_cereal coffee at_home_crackers carbonated_soft_drinks \
  --experiments budget brand flavor size price size_weight \
  --output-root generate_image/output/runs/baseline_setting/full_YYYYMMDD \
  --generate \
  --workers 3 \
  --max-in-flight-per-key 1 \
  --min-delay-per-key-seconds 2 \
  --resume \
  --skip-existing \
  --keep-going
```

`--workers` 是全局最大并发子进程数；不传时默认等于加载到的 API key 数，没有多 key 时为 `1`。`--max-in-flight-per-key` 控制同一个 key 同时跑多少个请求，建议先保持 `1`。`--min-delay-per-key-seconds` 控制同一个 key 两次请求启动之间的最小间隔。并发调度会保留 edit 依赖关系：需要先生成原始图的样本不会在原图成功前启动，如果原图失败，后续 edit 样本会标为 `blocked`，可用 `--retry-failed-only` 续跑。

Eye-level 专项实验：

```bash
python generate_image/eye_level_test_20260719/run_eye_level_test.py
```

## 检查入口

以下脚本会真实调用 OpenRouter：

```bash
python generate_image/test_generate_image_mode.py
python generate_image/test_price_only_edit_mode.py
```

## 输出目录

`generate_image/output/` 已按数据集常见交付方式预置为：

```text
output/
  runs/                 # 原始生成 run；脚本 output-root 默认写这里
  staging/              # 多 run 汇总、去重、改名、质检的临时区
  datasets/             # 可交付的数据集版本
    shelf_choice_v0/
      images/generated/
      images/reference_sheets/
      annotations/
      manifests/
      metadata/
      splits/
      provenance/
      qa/
      exports/
  archive/              # 废弃或旧版本 run
```

正式流程建议：

1. 生成脚本输出到 `output/runs/<run_family>/<run_id>/`。
2. 选中的样本进入 `output/staging/` 做合并和质检。
3. 交付版本整理到 `output/datasets/<dataset_name>_<version>/`。

## 输出约定

通用主入口会保存：

- 主图：`*.png`
- 请求：`*_请求.json` 或显式 `--request-output-file`
- 商品参考图：`*_商品参考.png`

批量实验会按 `output-root` 写入，默认位于 `generate_image/output/runs/`：

- `manifest.json`
- `requests/*.json`
- `screens/*.png`
- `run_status.json`
- `run_events.jsonl`
- `logs/*.log`
- `failed_items.json`

`generate_image/output/README.md` 中有更细的目录说明和推荐命令。

## 当前实验字段

核心支持字段：

- `sku_id`
- `item`
- `category_name`
- `base_price`
- `price`
- `promotion`
- `bestseller_badge`
- `size`
- `flavor`
- `weight`
- `position`
- `product_image`

当前 minimum-capability 和 Baseline Setting 不使用 `color`、`rating`、`reviews`、`number_of_reviews`、`inventory_remaining` 作为 request SKU 字段。
