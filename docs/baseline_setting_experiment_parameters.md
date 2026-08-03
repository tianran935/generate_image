# Baseline Setting 实验参数

本文档对应 `generate_image/experiments/run_baseline_setting_images.py` 和 `generate_image/experiments/build_min_capability_requests.py` 的当前实现。

## 1. 默认实验集合

`DEFAULT_EXPERIMENTS`:

```text
budget brand flavor size raw_price unit_price price size_weight
```

其中 `raw_price` 和 `unit_price` 是 budget 的两个子实验；脚本层面仍保留独立 subtest 名称，便于构造 request 和定位错误。

`core` 每个 dataset 每个 subtest 1 张；`full` / `all` 每个 dataset 每个 subtest 2 张。

## 2. SKU 字段

Baseline Setting 复用 minimum-capability 的 request SKU 白名单：

```text
sku_id
item
category_name
base_price
price
promotion
bestseller_badge
size
flavor
weight
position
product_image
```

不传入 `color`、`rating`、`reviews`、`number_of_reviews`、`inventory_remaining`。`product_number` 只从 `skus` 顺序派生，写入 manifest 的 `correct_product_number`，不写入 SKU。

## 3. Baseline Family

Assortment baseline:

- 用于 instruction following：`budget` family、`brand`, `flavor`, `size`。
- `budget` family 包含三个脚本 subtest：`budget`, `raw_price`, `unit_price`。
- 每张图 8 个不同真实 SKU。
- 每个 SKU 必须有 `product_image`。
- `promotion=none`，`bestseller_badge=none`。
- `position` 固定为 2x4。

Identical option baseline:

- 用于 `price`, `size_weight`。
- 选择一个有 `product_image` 且能生成 `weight` 的 anchor SKU。
- 复制为 8 个 option。
- `price` rationality 只改变 `price`。
- `size_weight` rationality 固定 `price`，只改变 `size` 和 `weight`。

## 4. 图上标签

主货架 tag 必须像真实超市 shelf rail 上的纸质价签。每个 focal product 正下方 1 个 tag。

tag 字段：

```text
price
category_name
item
flavor
size
```

不在图片中写 shopper instruction、task title、解释性文字、SKU ID、row/column 编号或 `product_number`。图片中不显示库存差异、促销贴纸或热卖 badge。

## 5. 正确答案规则

1. instruction following

Budget:

- `budget`: 唯一 `price <= target budget` 的 SKU。
- `raw_price`: `budget` 的子实验，唯一 `base_price` 最低的 SKU。
- `unit_price`: `budget` 的子实验，唯一 `base_price / weight` 最低的 SKU。

Other instruction following:

- `brand`: `item`/包装图推断出的目标品牌唯一 SKU。
- `flavor`: 唯一 `flavor == target flavor` 的 SKU。
- `size`: 唯一 `size > target size` 或者 `size < target size` 的 SKU。

2. Basic rationality:

- `price`: 同一 anchor SKU 的 8 个 option 中 `price` 最低。
- `size_weight`: 同一 anchor SKU 的 8 个 option 中 `weight` 最大，且所有 option `price` 相同。

## 6. 逐变量随机化方式

随机化入口是 `random.Random(--seed)`，默认 seed 为 `20260731`。Baseline Setting 先调用 minimum-capability payload builder 生成结构化 request，再由 runner 把所有样本转成 edit request。因此，变量随机化主要发生在 `build_min_capability_requests.py`，runner 只负责筛选实验、分组、写文件、以及绑定统一基准图。

### 6.1 全局规则

| 项目                                                                               | 当前实现                                                                                             |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| 随机数                                                                             | 单个 seeded RNG，按 dataset 顺序和 subtest 构造顺序连续使用。                                        |
| `scenario-set core`                                                              | 每个 dataset 每个 subtest 1 个 variant；`price` 只包含 `adjusted_low`。                          |
| `scenario-set full/all`                                                          | 每个 dataset 每个 subtest 2 个 variant；`price` 包含 `adjusted_low` 和 `adjusted_high`。       |
| SKU 候选顺序                                                                       | 读取`pic_reference/<dataset>/<csv_name>` 后保留 CSV 顺序；没有商品图的 row 会被过滤掉。            |
| 货架位置                                                                           | 固定 2x4：按最终`skus` 顺序映射到 row 1 col 1-4、row 2 col 1-4。                                   |
| SKU 排列随机化                                                                     | 多数场景先选出 8 个 row 或 8 个 option，再用 seeded RNG`shuffle` 打乱；位置由 shuffle 后顺序决定。 |
| `promotion`                                                                      | 固定为`none`，不随机化。                                                                           |
| `bestseller_badge`                                                               | 固定为`none`，不随机化。                                                                           |
| `inventory_remaining`, `color`, `rating`, `reviews`, `number_of_reviews` | 不进入 request SKU 字段，不随机化。                                                                  |
| `product_image`                                                                  | 按 UPC 优先、再按`rankXX` 匹配，确定性选择，不随机化。                                             |
| `brand`, `flavor`, `size`, `weight`                                        | 从商品描述和 rank 规则确定性推断；其中`weight` 从 `size` 解析。                                  |

### 6.2 Dataset 固定参数

| dataset                    | `default_budget` | `base_price` | preferred brands                         | preferred flavors                                    | preferred sizes                                         |
| -------------------------- | -----------------: | -------------: | ---------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------- |
| `at_home_crackers`       |               3.00 |           4.29 | Nabisco, Pepperidge Farm, Sunshine, Ritz | Wheat, Honey, Cheese, Plain                          | 7 oz box, 8.8 oz box, 10 oz box, 13.7 oz box            |
| `carbonated_soft_drinks` |               4.00 |           5.99 | Coca-Cola, Pepsi, Sprite, Dr Pepper      | Cola, Diet Cola, Lemon-Lime, Dr Pepper               | 12 fl oz can, 20 fl oz bottle, 2 L bottle, 12 pack cans |
| `coffee`                 |               7.00 |           9.99 | Peet's, Starbucks, Folgers, Yuban        | French Roast, House Blend, Decaf, Breakfast Blend    | 10 oz bag, 12 oz bag, 16 oz bag, 18 ct pods             |
| `cold_cereal`            |               3.50 |           4.99 | General Mills, Kellogg's, Post, Quaker   | Original, Honey Nut, Frosted Wheat, Cinnamon         | 10.7 oz box, 12 oz box, 14.8 oz box, 18 oz box          |
| `tortilla_chips`         |               3.00 |           4.49 | Tostitos, Doritos, Mission, Santitas     | Restaurant Style, Scoops, Nacho Cheese, Hint of Lime | 8.5 oz bag, 9.25 oz bag, 10 oz bag, 13 oz bag           |

### 6.3 Subtest 逐项参数生成

| subtest         | SKU / option 选择                                                                                                                                                                                 | 目标值                                         | 价格 / 尺寸生成                                                                                                                                                                                                                                                                                                 | 正确答案位置                                                                                              |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `budget`      | 取 CSV 有图 row 的`rows[variant:variant+8]`；不足 8 个时回退 `rows[:8]`；之后 `rng.shuffle`。                                                                                               | `budget = default_budget + 0.50 * variant`。 | 视觉位置`index - 1 == variant % 8` 的商品为目标，`price = budget - 0.20`；其他商品 `price = budget + 0.45 + 0.18 * index`。`base_price` 默认等于 `price`。                                                                                                                                            | 由 shuffle 后的 SKU 顺序和固定`target_index = variant % 8` 决定；每个场景唯一一个 `price <= budget`。 |
| `brand`       | 目标 brand 从 preferred list 优先选；若 preferred 不足，再按其他 brand 字母序补齐。每个目标值要求至少 1 个目标 SKU 且至少 7 个非目标 SKU。选`targets[0] + non_targets[:7]` 后 `rng.shuffle`。 | `target_value = brand`。                     | 每个 SKU`price = base_price + 0.12 * ((index + variant) % 5)`；`base_price` 默认等于 `price`。                                                                                                                                                                                                            | shuffle 后唯一一个 infer_brand(`item`) 等于目标 brand 的 SKU。                                          |
| `flavor`      | 与`brand` 相同，但字段换成 `flavor`，目标 flavor 从 preferred flavors 优先选，再按其他 flavor 字母序补齐。                                                                                    | `target_value = flavor`。                    | 每个 SKU`price = base_price + 0.12 * ((index + variant) % 5)`。                                                                                                                                                                                                                                               | shuffle 后唯一一个`flavor == target_value` 的 SKU。                                                     |
| `size`        | 与`brand` 相同，但字段换成 `size`，目标 size 从 preferred sizes 优先选，再按其他 size 字母序补齐。                                                                                            | `target_value = size`。                      | 每个 SKU`price = base_price + 0.12 * ((index + variant) % 5)`。                                                                                                                                                                                                                                               | shuffle 后唯一一个`size == target_value` 的 SKU。                                                       |
| `raw_price`   | 取`rows[variant:variant+8]`；不足 8 个时回退 `rows[:8]`；之后 `rng.shuffle`。                                                                                                               | `budget` 子实验：lowest raw price。          | 视觉位置`index - 1 == variant % 8` 的商品为目标，`price = base_price = config.base_price - 0.50`；其他商品 `price = base_price = config.base_price + 0.20 + 0.17 * index`。                                                                                                                               | 由 shuffle 后 SKU 顺序和固定`target_index = variant % 8` 决定；唯一最低 `base_price`。                |
| `unit_price`  | 先过滤出`weight > 0` 的 row；取 `weighted[variant:variant+8]`；不足 8 个时回退 `weighted[:8]`；之后 `rng.shuffle`。                                                                       | `budget` 子实验：lowest unit price。         | 视觉位置`index - 1 == variant % 8` 的商品为目标，单位价系数 `0.18`；其他商品单位价系数 `0.26 + 0.015 * index`。最终 `price = base_price = max(0.49, round(weight * unit_price, 2))`。                                                                                                                   | 由 shuffle 后 SKU 顺序和固定`target_index = variant % 8` 决定；唯一最低 `base_price / weight`。       |
| `price`       | 使用同一个 anchor SKU，`anchor = rows[--price-anchor-index]`，默认第 0 个有图 row。复制成 8 个 option。                                                                                         | 固定任务为 lowest price。                      | `adjusted_low`: `[base - 0.03, base + 0.02, base + 0.04, base + 0.05, base + 0.06, base + 0.07, base + 0.08, base + 0.09]`。`adjusted_high`: `[base - 1.20, base - 0.55, base - 0.15, base + 0.25, base + 0.80, base + 1.15, base + 1.60, base + 2.10]`。价格列表先 `rng.shuffle` 再分配到 8 个位置。 | shuffle 后价格最低的 option；所有 option 使用同一商品图和同一基础 SKU。                                   |
| `size_weight` | 使用同一个 anchor SKU，`anchor = rows[--price-anchor-index]`，默认第 0 个有图 row。复制成 8 个 option。                                                                                         | 固定任务为 largest weight。                    | 每个 dataset 有固定 8 个 size option。`variant` 为奇数时先反转 size 列表；随后 `rng.shuffle`。所有 option `price = base_price = config.base_price`。`weight` 从 size 解析。                                                                                                                             | shuffle 后`weight` 最大的 option；所有 option 价格相同。                                                |

### 6.4 `size_weight` 尺寸候选

| dataset                    | variant 0 顺序                                                                                                |
| -------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `at_home_crackers`       | 6 oz box, 7 oz box, 8 oz box, 8.8 oz box, 10 oz box, 12 oz box, 13.7 oz box, 16 oz box                        |
| `carbonated_soft_drinks` | 8 fl oz can, 12 fl oz can, 16 fl oz can, 20 fl oz bottle, 1 L bottle, 1.25 L bottle, 1.5 L bottle, 2 L bottle |
| `coffee`                 | 8 oz bag, 10 oz bag, 12 oz bag, 14 oz bag, 16 oz bag, 18 oz bag, 20 oz bag, 24 oz bag                         |
| `cold_cereal`            | 8.9 oz box, 10.7 oz box, 12 oz box, 13.5 oz box, 14.8 oz box, 16 oz box, 18 oz box, 21 oz box                 |
| `tortilla_chips`         | 7 oz bag, 8.5 oz bag, 9.25 oz bag, 10 oz bag, 11 oz bag, 12 oz bag, 13 oz bag, 15 oz bag                      |

`variant 1` 先把上表顺序反转，再做 seeded shuffle。

### 6.5 Edit-only 关系

Baseline Setting request 的结构化变量在写 request 时已经固定。当前 runner 是 edit-only：必须通过 `--baseline-image` 或兼容别名 `--original-image` 提供一张基准货架图；所有 payload 都写为 `mode=edit`，`input_image` 都指向这张基准图，不再自动生成第 1 张原始图。`--edit-source` 和 `--edit-source-scope` 仅保留为 manifest 兼容字段，不改变当前 edit-only 行为。

## 7. 从数据到分析

Baseline Setting 的分析不要直接依赖图片文件名猜答案，而是以 `manifest.json` 和每个样本的 `request_file` 为准。图片只作为被测模型的视觉输入；答案、SKU 顺序和正确选项都从结构化数据中恢复。

### 7.1 分析输入与样本表

每个 run 至少保留三类文件：

```text
manifest.json
<dataset>/<experiment>/requests/*.json
<dataset>/<experiment>/screens/*.png
```

分析前先把它们展开成 item-level 样本表，每行 1 张图：

| 字段                                                                     | 来源                            | 用途                                                                       |
| ------------------------------------------------------------------------ | ------------------------------- | -------------------------------------------------------------------------- |
| `run_id`                                                               | output root 或 manifest         | 区分批次。                                                                 |
| `dataset`, `category`, `experiment`, `scenario_id`, `item_key` | manifest                        | 分组汇总。                                                                 |
| `baseline_family`                                                      | manifest                        | 区分 assortment / identical option。                                       |
| `prompt_instruction`                                                   | manifest 或 request             | 发给被测模型的 shopper instruction。                                       |
| `screen_file`                                                          | manifest                        | 被测模型看到的图片。                                                       |
| `skus`                                                                 | `request_file`                | 恢复 8 个 option 的属性和顺序。                                            |
| `correct_sku_id`                                                       | manifest 或 request             | 主答案键。                                                                 |
| `correct_product_number`                                               | manifest 或由`skus` 顺序派生  | 内部 option index，范围 1-8。                                              |
| `correct_row`, `correct_col`                                         | `correct_product_number` 派生 | 视觉位置答案，`row = ceil(index / 4)`，`col = ((index - 1) % 4) + 1`。 |

注意：`product_number` 不出现在图片 tag 上，也不写入 SKU。它只能作为内部顺序编号使用。给被测模型的回答接口应优先要求返回 `row` / `col`，不要要求模型读出或选择图片中不存在的 `product_number`。

### 7.2 被测模型输入与输出

对每张图，给被测模型的输入只包含：

1. `screen_file` 对应图片。
2. `prompt_instruction` 对应的 shopper instruction。
3. 固定回答格式说明。

不要把 `correct_sku_id`、`correct_product_number`、完整 `skus`、答案规则或隐藏目标值发给被测模型。推荐输出格式：

```json
{
  "row": 1,
  "col": 3,
  "confidence": 0.72,
  "reason": "optional short reason"
}
```

评分脚本只把 `row` / `col` 作为主选择字段。若模型额外输出商品名、价格或解释，可保留用于错误分析，但不要用解释覆盖主选择，除非主选择无法解析并且你明确开启了人工或规则化 fallback。

### 7.3 图片 QA 过滤

模型评分前先做图片级 QA，并在结果中同时记录 raw score 和 QA-filtered score。建议把以下情况标记为 `qa_fail`，正式主结果中剔除或重新生成：

- 图片缺失、为空、损坏，或 `screen_file` 和 manifest 对不上。
- 不是 2x4、不是 8 个 focal products，或商品和 tag 不能一一对应。
- tag 缺少决策字段：`price`, `category_name`, `item`, `flavor`, `size`。
- tag 出现禁止字段或文字：shopper instruction、task title、SKU ID、row/column 编号、`product_number`、库存、rating、review 信息。
- 正确答案所需字段在图中不可读，或视觉内容与 request 明显冲突。
- 对 basic rationality，8 个 option 没有保持同一 anchor SKU 的外观，导致变量不再只来自 `price` 或 `size` / `weight`。

### 7.4 Instruction following 打分

Instruction following 包含：

```text
budget brand flavor size
```

其中 budget family 下有三个脚本 subtest：

```text
budget raw_price unit_price
```

这些任务的共同评分逻辑：

1. 从模型输出解析 `row` / `col`，映射为 `chosen_product_number = (row - 1) * 4 + col`。
2. 从 `request_file.skus` 按顺序取出 `chosen_sku`。
3. 用 `correct_sku_id` / `correct_product_number` 判定 exact match。
4. 同时按规则重新计算 winner set，确认该样本仍然只有 1 个正确答案；若不是唯一答案，标记为 `invalid_item`，不进入主分析。

逐任务规则：

| task family | subtest        | 模型需要遵循的指令           | scoring key                                                             |
| ----------- | -------------- | ---------------------------- | ----------------------------------------------------------------------- |
| `budget`  | `budget`     | 在预算内选择商品。           | 唯一`price <= target_value` 的 SKU。                                  |
| `budget`  | `raw_price`  | 选择货架原始价格最低的商品。 | 唯一`base_price` 最低的 SKU；当前正式场景中 `price == base_price`。 |
| `budget`  | `unit_price` | 选择单位价格最低的商品。     | 唯一`base_price / weight` 最低的 SKU。                                |
| `brand`   | `brand`      | 选择目标品牌。               | 唯一`infer_brand(dataset, item) == target_value` 的 SKU。             |
| `flavor`  | `flavor`     | 选择目标口味。               | 唯一`flavor == target_value` 的 SKU。                                 |
| `size`    | `size`       | 选择目标规格。               | 唯一`size == target_value` 的 SKU。                                   |

主指标：

- `budget_accuracy`: `budget`, `raw_price`, `unit_price` 三个子实验的 macro accuracy。
- `instruction_following_accuracy`: 四个 top-level task family 的 macro accuracy，即 `budget_accuracy`, `brand_accuracy`, `flavor_accuracy`, `size_accuracy` 的平均。
- `accuracy_by_subtest`: 每个 subtest 单独 accuracy。
- `accuracy_by_task_family`: `budget`, `brand`, `flavor`, `size` 四个 family 单独 accuracy。
- `accuracy_by_dataset`: 每个 dataset 内的 accuracy。
- `invalid_response_rate`: 模型输出无法解析为合法 `row` / `col` 的比例。
- `qa_fail_rate`: 生成图片未通过 QA 的比例，和模型能力分开报告。

### 7.5 Basic rationality 打分

Basic rationality 包含：

```text
price size_weight
```

这两类样本都使用 identical option baseline：8 个 option 来自同一个 anchor SKU，因此被测模型不应依赖品牌、包装差异或喜好，只需要做基础理性比较。

逐任务规则：

| subtest         | 控制变量                                                             | scoring key                    | 解释                               |
| --------------- | -------------------------------------------------------------------- | ------------------------------ | ---------------------------------- |
| `price`       | 同一 SKU、同一包装/口味/规格，只改变`price`。                      | 唯一`price` 最低的 option。  | 检查模型是否选择更低价格。         |
| `size_weight` | 同一 SKU、所有 option`price` 相同，只改变 `size` 和 `weight`。 | 唯一`weight` 最大的 option。 | 检查模型是否在同价下选择更大规格。 |

主指标：

- `basic_rationality_accuracy`: `price` 和 `size_weight` 的 macro accuracy。
- `price_accuracy`: 最低价选择准确率。
- `size_weight_accuracy`: 同价最大规格选择准确率。
- `dominance_violation_rate`: 模型没有选择被严格支配选项中的最优项的比例。这里等价于 `1 - basic_rationality_accuracy`，但建议单独命名，便于后续加入更多 rationality task。

### 7.6 汇总与诊断

建议输出以下分析文件：

```text
responses.jsonl
scored_results.jsonl
summary_by_task.csv
summary_by_dataset.csv
summary_by_model.csv
position_bias.csv
qa_flags.jsonl
error_cases.csv
```

`scored_results.jsonl` 每行至少包含：

```text
run_id
model
dataset
experiment
scenario_id
item_key
screen_file
prompt_instruction
chosen_row
chosen_col
chosen_product_number
chosen_sku_id
correct_row
correct_col
correct_product_number
correct_sku_id
is_correct
is_parseable
qa_status
error_type
```

汇总时建议同时报告 micro 和 macro：

- micro accuracy: 所有有效样本直接平均。
- macro by subtest: 先算每个脚本 subtest accuracy，再对 subtest 平均；用于定位具体实验难点。
- macro by task family: 先把 `raw_price` 和 `unit_price` 合并回 `budget` family，再与 `brand`、`flavor`、`size` 平均；这是 instruction following 的主口径。
- macro by dataset: 先算每个 dataset accuracy，再对 dataset 平均；用于避免某个品类样本量更大时支配结果。
- 置信区间：样本数较小时用 bootstrap；只汇总二元正确率时也可报告 Wilson interval。

诊断表重点看：

- `position_bias`: 模型选择 row/col 的分布是否偏向左上、中心或第一行。
- `accuracy_by_correct_position`: 正确答案在不同位置时的准确率。
- `confusion_by_attribute`: instruction following 中错在 budget threshold、raw price、unit price、品牌、口味还是规格。
- `qa_filtered_vs_raw`: 剔除图片 QA 失败后结果是否显著变化。
- `generation_order`: edit-only 批量生成中后续图片是否更容易出现标签漂移或可读性下降。

错误类型建议统一成：

```text
correct
invalid_response
wrong_position
wrong_attribute
price_reading_error
unit_price_calculation_error
size_weight_comparison_error
image_qa_fail
ambiguous_or_non_unique_key
```

### 7.7 最终报告口径

正式报告中把两类能力分开写：

- Instruction following: 报告 `budget`, `brand`, `flavor`, `size` 四个 top-level task family 的 macro accuracy；其中 `budget` 需要继续拆出 `budget`, `raw_price`, `unit_price` 三个子实验明细。
- Basic rationality: 报告 `price`, `size_weight` 两项的 macro accuracy，并给出 dominance violation rate。

不要把图片生成失败、QA 失败和模型选择错误混在一个数里。推荐同时给：

1. generation success rate。
2. QA pass rate。
3. parseable response rate。
4. QA-filtered task accuracy。
5. raw task accuracy。

这样可以区分三类问题：生图是否可靠、模型是否按格式回答、模型是否真正完成选择任务。

## 8. 推荐命令

构造 request，不生图：

```bash
python generate_image/run_baseline_setting_images.py \
  --scenario-set core \
  --datasets tortilla_chips \
  --experiments budget brand flavor size raw_price unit_price price size_weight \
  --baseline-image path/to/baseline.png \
  --output-root generate_image/output/runs/baseline_setting/schema_check
```

批量生图：

```bash
python generate_image/run_baseline_setting_images.py \
  --scenario-set full \
  --datasets tortilla_chips cold_cereal coffee at_home_crackers carbonated_soft_drinks \
  --experiments budget brand flavor size raw_price unit_price price size_weight \
  --baseline-image path/to/baseline.png \
  --output-root generate_image/output/runs/baseline_setting/full_YYYYMMDD \
  --generate \
  --resume \
  --skip-existing \
  --keep-going
```
