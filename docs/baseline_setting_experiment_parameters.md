# Baseline Setting 实验参数

本文档对应 `generate_image/experiments/run_baseline_setting_images.py` 和 `generate_image/experiments/build_min_capability_requests.py` 的当前实现。

## 1. 默认实验集合

`DEFAULT_EXPERIMENTS`:

```text
budget brand flavor size price size_weight
```

其中 `raw_price` 和 `unit_price` 是 `budget` 的两个子实验。选择 top-level experiment `budget` 时会同时构造 `raw_price`, `unit_price` 两个 subtest；脚本层面仍允许显式选择 `raw_price` 或 `unit_price`，便于单独调试。

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
- `budget` family 包含两个脚本 subtest：`raw_price`, `unit_price`。
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
item
price
category_name
flavor
size
```

Baseline Setting 的主 shelf tag 使用固定 5 行格式：白色纸质 tag，位于每个商品正下方并居中贴在 shelf rail 上；黑色高对比水平文字；Line 1 centered: item/name，Line 2 centered: price（两位小数且最突出），Line 3 centered: category_name，Line 4 centered: flavor，Line 5 centered: size。该规则写入每个 request 的 `label_prompt_spec`，不写入 SKU 字段。

不在图片中写 shopper instruction、task title、解释性文字、SKU ID、row/column 编号或 `product_number`。图片中不显示库存差异、促销贴纸或热卖 badge。

## 5. 正确答案规则

1. instruction following

Budget:

- `raw_price`: `budget` 的子实验，唯一 `base_price <= target budget` 的 SKU。
- `unit_price`: `budget` 的子实验，唯一 `base_price / weight <= target budget` 的 SKU。

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

| 项目                                                                               | 当前实现                                                                                                                        |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| 随机数                                                                             | 单个 seeded RNG，按 dataset 顺序和 subtest 构造顺序连续使用。                                                                   |
| `scenario-set core`                                                              | 每个 dataset 每个 subtest 1 个 variant；`price` 只包含 `adjusted_low`。                                                     |
| `scenario-set full/all`                                                          | 每个 dataset 每个 subtest 2 个 variant；`price` 包含 `adjusted_low` 和 `adjusted_high`。                                  |
| SKU 候选顺序                                                                       | 读取`pic_reference/<dataset>/<csv_name>` 后保留 CSV 顺序；没有商品图的 row 会被过滤掉。                                       |
| 货架位置                                                                           | 固定 2x4：按最终`skus` 顺序映射到 row 1 col 1-4、row 2 col 1-4。                                                              |
| SKU 排列随机化                                                                     | 多数场景先选出 8 个 row 或 8 个 option，再用 seeded RNG`shuffle` 打乱；位置由 shuffle 后顺序决定。                            |
| 目标位置随机化                                                                     | `raw_price`, `unit_price` 在 SKU shuffle 后再用 seeded RNG 从 8 个最终位置中随机抽取目标位置；不由`variant` 固定。        |
| 非目标价格分配                                                                     | 先生成一组保证高于目标/预算的价格或单位价梯度，再用 seeded RNG 打乱后分配到非目标位置；价格不再是视觉位置`index` 的线性函数。 |
| `promotion`                                                                      | 固定为`none`，不随机化。                                                                                                      |
| `bestseller_badge`                                                               | 固定为`none`，不随机化。                                                                                                      |
| `inventory_remaining`, `color`, `rating`, `reviews`, `number_of_reviews` | 不进入 request SKU 字段，不随机化。                                                                                             |
| `product_image`                                                                  | 按 UPC 优先、再按`rankXX` 匹配，确定性选择，不随机化。                                                                        |
| `brand`, `flavor`, `size`, `weight`                                        | 从商品描述和 rank 规则确定性推断；其中`weight` 从 `size` 解析。                                                             |

### 6.2 Dataset 固定参数

| dataset                    | `default_budget` | `base_price` | preferred brands                         | preferred flavors                                    | preferred sizes                                         |
| -------------------------- | -----------------: | -------------: | ---------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------- |
| `at_home_crackers`       |               3.00 |           4.29 | Nabisco, Pepperidge Farm, Sunshine, Ritz | Wheat, Honey, Cheese, Plain                          | 7 oz box, 8.8 oz box, 10 oz box, 13.7 oz box            |
| `carbonated_soft_drinks` |               4.00 |           5.99 | Coca-Cola, Pepsi, Sprite, Dr Pepper      | Cola, Diet Cola, Lemon-Lime, Dr Pepper               | 12 fl oz can, 20 fl oz bottle, 2 L bottle, 12 pack cans |
| `coffee`                 |               7.00 |           9.99 | Peet's, Starbucks, Folgers, Yuban        | French Roast, House Blend, Decaf, Breakfast Blend    | 10 oz bag, 12 oz bag, 16 oz bag, 18 ct pods             |
| `cold_cereal`            |               3.50 |           4.99 | General Mills, Kellogg's, Post, Quaker   | Original, Honey Nut, Frosted Wheat, Cinnamon         | 10.7 oz box, 12 oz box, 14.8 oz box, 18 oz box          |
| `tortilla_chips`         |               3.00 |           4.49 | Tostitos, Doritos, Mission, Santitas     | Restaurant Style, Scoops, Nacho Cheese, Hint of Lime | 8.5 oz bag, 9.25 oz bag, 10 oz bag, 13 oz bag           |

这里的 `default_budget` 和 `base_price` 不是同一列价格的上下界关系。`default_budget` 只用于 `budget` family 生成阈值：`raw_price` 中它是 shelf price budget，`unit_price` 中它是 unit price budget。`base_price` 是非 budget 任务和 basic rationality 任务使用的默认/回退货架价，例如 `brand`, `flavor`, `size`, `price`, `size_weight`；在 `raw_price` 和 `unit_price` 子实验里，SKU 的 `price` / `base_price` 会按 budget offset 规则重写，所以不要求 6.2 里的 `base_price <= default_budget`。

### 6.3 Task family / subtest 逐项参数生成

| task family     | subtest         | SKU / option 选择                                                                                                                                                                                                          | 目标值                                                                              | 价格 / 尺寸生成                                                                                                                                                                                                                                                                                                                            | 正确答案位置                                                                                                    |
| --------------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| `budget`      | `raw_price`   | 取 CSV 有图 row 的`rows[variant:variant+8]`；不足 8 个时回退 `rows[:8]`；之后 `rng.shuffle`。                                                                                                                        | `budget = default_budget + 0.50 * variant`。                                      | SKU shuffle 后从 8 个最终位置中随机抽 1 个目标位置，目标`price = base_price = budget - random_offset`，其中 `random_offset` 从 `[0, budget)` 随机抽取；其他商品先生成 7 个唯一随机 offset，`price = base_price = budget + random_offset`，offset 从 `[0.05, 1.80]` 抽取并打乱分配。                                              | 目标位置由 seeded RNG 决定；每个场景唯一一个`base_price <= budget`。                                          |
| `budget`      | `unit_price`  | 先过滤出`weight > 0` 的 row；取 `weighted[variant:variant+8]`；不足 8 个时回退 `weighted[:8]`；之后 `rng.shuffle`。                                                                                                | `budget = default_budget + 0.50 * variant`。                                      | SKU shuffle 后从 8 个最终位置中随机抽 1 个目标位置，目标`unit_price = budget - random_offset`，其中 `random_offset` 从 `[0, budget)` 随机抽取；其他商品先生成 7 个唯一随机 offset，`unit_price = budget + random_offset`，offset 从 `[0.05, 1.80]` 抽取并打乱分配。最终 `price = base_price = round(unit_price * weight, 2)`。 | 目标位置由 seeded RNG 决定；每个场景唯一一个`base_price / weight <= budget`。                                 |
| `brand`       | `brand`       | 目标 brand 从 preferred list 优先选；若 preferred 不足，再按其他 brand 字母序补齐。每个目标值要求至少 1 个目标 SKU 且至少 7 个非目标 SKU。选`targets[0] + non_targets[:7]` 后 `rng.shuffle`。                          | `target_value = brand`。                                                          | 不做人为价格变化；每个 SKU 用数据里的原始价格作为`price`。原始价格按 `gross_amt / item_qty` 估算；若无有效 `gross_amt`，用 `net_amt / item_qty`；若数据没有金额列或不可解析，回退 dataset 默认 `base_price`。`base_price` 默认等于 `price`。                                                                                 | shuffle 后唯一一个 infer_brand(`item`) 等于目标 brand 的 SKU。                                                |
| `flavor`      | `flavor`      | 与`brand` 相同，但字段换成 `flavor`，目标 flavor 从 preferred flavors 优先选，再按其他 flavor 字母序补齐。                                                                                                             | `target_value = flavor`。                                                         | 不做人为价格变化；每个 SKU 用数据里的原始价格作为`price`，估算口径同 `brand`。`base_price` 默认等于 `price`。                                                                                                                                                                                                                      | shuffle 后唯一一个`flavor == target_value` 的 SKU。                                                           |
| `size`        | `size`        | 只使用可解析`weight` 的 row；`variant` 为偶数时构造 `greater_than`，奇数时构造 `less_than`。阈值 size 从 preferred sizes 优先选，再按其他 size 的解析重量补齐；选 1 个目标 SKU 和 7 个非目标 SKU 后 `rng.shuffle`。 | `target_value = size threshold`；`target_relation = greater_than / less_than`。 | 不做人为价格变化；每个 SKU 用数据里的原始价格作为`price`，估算口径同 `brand`。`base_price` 默认等于 `price`。                                                                                                                                                                                                                      | shuffle 后唯一一个 SKU 满足`size > target_value` 或`size < target_value`；实际比较使用解析出的 `weight`。 |
| `price`       | `price`       | 使用同一个 anchor SKU，`anchor = rows[--price-anchor-index]`，默认第 0 个有图 row。复制成 8 个 option。                                                                                                                  | 固定任务为 lowest price。                                                           | `adjusted_low`: `[base - 0.03, base + 0.02, base + 0.04, base + 0.05, base + 0.06, base + 0.07, base + 0.08, base + 0.09]`。`adjusted_high`: `[base - 1.20, base - 0.55, base - 0.15, base + 0.25, base + 0.80, base + 1.15, base + 1.60, base + 2.10]`。价格列表先 `rng.shuffle` 再分配到 8 个位置。                            | shuffle 后价格最低的 option；所有 option 使用同一商品图和同一基础 SKU。                                         |
| `size_weight` | `size_weight` | 使用同一个 anchor SKU，`anchor = rows[--price-anchor-index]`，默认第 0 个有图 row。复制成 8 个 option。                                                                                                                  | 固定任务为 largest weight。                                                         | 每个 dataset 有固定 8 个 size option。`variant` 为奇数时先反转 size 列表；随后 `rng.shuffle`。所有 option `price = base_price = config.base_price`。`weight` 从 size 解析。                                                                                                                                                        | shuffle 后`weight` 最大的 option；所有 option 价格相同。                                                      |

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

## 7. 从数据到评估

Baseline Setting 的评估以 `manifest.json` 和每个样本的 `request_file` 为准。图片只作为被测 AI 的视觉输入；正确答案、SKU 顺序、目标字段和目标值都从结构化文件恢复，不从图片文件名推断。

### 7.1 评估输入与 AI 输出

每个样本给 AI 的输入只包含：

- `screen_file` 对应图片。
- `prompt_instruction` 对应 shopper instruction。
- 固定回答格式说明。

AI 输出 JSON：

```json
{
  "row": 1,
  "col": 3,
  "confidence": 0.72,
  "reason": "optional short reason"
}
```

评分脚本把 `row` / `col` 映射回内部 option 顺序：

```text
chosen_product_number = (row - 1) * 4 + col
```

再用 `chosen_product_number` 从 `request_file.skus` 中取出 `chosen_sku`。`product_number` 仍然只从 `skus` 顺序派生，不写入 SKU，也不出现在图片 tag 上。

每条 scored result 保留：

```text
dataset
experiment
task_family
subtest
scenario_id
item_key
screen_file
prompt_instruction
chosen_row
chosen_col
chosen_product_number
chosen_sku_id
correct_product_number
correct_sku_id
is_parseable
is_correct
qa_status
error_type
```

### 7.2 Instruction following 评分

Instruction following 的 top-level family 是：

```text
budget brand flavor size
```

`budget` family 只有两个 subtest：

```text
raw_price unit_price
```

共同评分流程：

1. 解析 AI 输出的 `row` / `col`；无法解析或超出 2x4 范围时，记为 `invalid_response`。
2. 映射到 `chosen_product_number`，并取出 `chosen_sku`。
3. 用下表规则重新计算 winner set；如果 winner set 不是唯一项，样本标记为 `ambiguous_or_non_unique_key`，不进入主准确率。
4. 若 `chosen_sku_id == correct_sku_id`，则 `is_correct = true`。

| task family | subtest        | scoring key                                                                                                               |
| ----------- | -------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `budget`  | `raw_price`  | 唯一`base_price <= target_value` 的 SKU。                                                                               |
| `budget`  | `unit_price` | 唯一`base_price / weight <= target_value` 的 SKU。                                                                      |
| `brand`   | `brand`      | 唯一`infer_brand(dataset, item) == target_value` 的 SKU。                                                               |
| `flavor`  | `flavor`     | 唯一`flavor == target_value` 的 SKU。                                                                                   |
| `size`    | `size`       | 唯一按`target_relation` 满足`size > target_value` 或`size < target_value` 的 SKU；实际比较使用解析出的 `weight`。 |

这里 `raw_price` 和 `unit_price` 的 `target_value` 都是 budget threshold，例如 `$3.00`。
这里 `size` 的 `target_value` 是 size threshold，`target_relation` 为 `greater_than` 或 `less_than`。

### 7.3 Basic rationality 评分

Basic rationality 只包含：

```text
price size_weight
```

这两个任务不是 preference following，而是 dominance / rationality 检查。

| subtest         | scoring key                                                |
| --------------- | ---------------------------------------------------------- |
| `price`       | 8 个 option 是同一 anchor SKU；正确项为唯一最低`price`。 |
| `size_weight` | 8 个 option 价格相同；正确项为唯一最大`weight`。         |

同样先从 AI 的 `row` / `col` 得到 `chosen_product_number`，再和 manifest/request 中的 `correct_sku_id` 或 `correct_product_number` 比较。

### 7.4 汇总指标

- `instruction_following_accuracy`: `budget_accuracy`, `brand_accuracy`, `flavor_accuracy`, `size_accuracy` 的 macro average。
- `budget_accuracy`: `raw_price_accuracy` 和 `unit_price_accuracy` 的 macro average。
- `basic_rationality_accuracy`: `price_accuracy` 和 `size_weight_accuracy` 的 macro average。
- `invalid_response_rate`: AI 输出无法解析为合法 `row` / `col` 的比例。
- `qa_fail_rate`: 图片未通过 QA （quality assurance）比例。
- `raw_accuracy`: 不过滤 QA fail 的总体准确率。
- `qa_filtered_accuracy`: 剔除 QA fail 后的准确率。

辅助诊断建议按 `dataset`, `task_family`, `subtest`, `correct_product_number`, `chosen_product_number` 分组，检查品类差异、任务差异和位置偏差。

### 7.5 QA 与错误类型

正式主结果剔除或单独报告以下 `qa_fail` 样本：

- 图片缺失、为空、损坏，或 `screen_file` 和 manifest 对不上。
- 图片不是 2x4、不是 8 个 focal products，或商品和 tag 不能一一对应。
- tag 缺少决策字段：`price`, `category_name`, `item`, `flavor`, `size`。
- tag 出现 forbidden fields：shopper instruction、task title、SKU ID、row/column 编号、`product_number`、库存、rating、review 信息。
- 决策所需字段不可读，或视觉内容与 request 明显冲突。

错误类型建议统一为：

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

## 8. 推荐命令

构造 request，不生图：

```bash
python generate_image/run_baseline_setting_images.py \
  --scenario-set core \
  --datasets tortilla_chips \
  --experiments budget brand flavor size price size_weight \
  --baseline-image path/to/baseline.png \
  --output-root generate_image/output/runs/baseline_setting/schema_check
```

批量生图：

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
