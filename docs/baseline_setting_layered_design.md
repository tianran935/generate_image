
# Baseline Setting 分层实验设计

本文档是 `baseline_setting_experiment_parameters.md` 的分层版：上层只记录全局 schema、baseline 类型、图片生成约束和实验集合；下层按 category 写每个实验的具体假定。完整实现细节仍以 `generate_image/experiments/build_min_capability_requests.py` 和 `generate_image/experiments/run_baseline_setting_images.py` 为准。

## 1. 上层定义

### 1.1 Request SKU 字段

每个 SKU 只允许以下字段：

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

不传入 `color`, `rating`, `reviews`, `number_of_reviews`, `inventory_remaining`。`product_number` 只从 `skus` 顺序派生，用于 manifest / scoring，不写入 SKU，也不出现在图片 tag 上。

### 1.2 图片生成基本信息

- 所有 Baseline Setting 图片固定为 2x4 shelf grid，共 8 个 focal products。
- 当前 runner 是 edit-only：必须通过 `--baseline-image` 或 `--original-image` 提供基准货架图；所有实验 request 都是基于该图的 edit request。
- 每个 focal product 正下方有一个真实货架风格 shelf tag。
- tag 只显示 `price`, `category_name`, `item`, `flavor`, `size`。
- 图中不显示 shopper instruction、task title、解释文字、SKU ID、row/column 编号、`product_number`、库存、rating、review、促销贴纸或热卖 badge。
- `promotion=none`，`bestseller_badge=none`。

### 1.3 Baseline 类型

| baseline type             | 用途                                        | 基本假定                                                         |
| ------------------------- | ------------------------------------------- | ---------------------------------------------------------------- |
| assortment baseline       | `budget`, `brand`, `flavor`, `size` | 每张图 8 个不同真实 SKU；正确答案由 instruction 指定的约束决定。 |
| identical option baseline | `price`, `size_weight`                  | 同一个 anchor SKU 复制为 8 个 option；只改变被测试变量。         |

### 1.4 实验集合

默认 top-level experiments：

```text
budget brand flavor size price size_weight
```

`budget` 是 top-level task family，下面只有两个 subtest：

```text
raw_price unit_price
```

能力分组：

| group                 | experiment / subtest  | 正确答案规则                                                                                     |
| --------------------- | --------------------- | ------------------------------------------------------------------------------------------------ |
| instruction following | `budget/raw_price`  | 唯一`base_price <= target budget` 的 SKU。                                                     |
| instruction following | `budget/unit_price` | 唯一`base_price / weight <= target budget` 的 SKU。                                            |
| instruction following | `brand`             | 唯一`infer_brand(dataset, item) == target brand` 的 SKU。                                      |
| instruction following | `flavor`            | 唯一`flavor == target flavor` 的 SKU。                                                         |
| instruction following | `size`              | 唯一满足`size > target size` 或 `size < target size` 的 SKU；实际比较用解析出的 `weight`。 |
| basic rationality     | `price`             | 同一 anchor SKU 的 8 个 option 中唯一最低`price`。                                             |
| basic rationality     | `size_weight`       | 同价条件下唯一最大`weight`。                                                                   |

### 1.5 Scenario 数量

| scenario set       | 每个 dataset 的样本                            |
| ------------------ | ---------------------------------------------- |
| `core`           | 每个 concrete subtest 1 个 variant，共 7 张。  |
| `full` / `all` | 每个 concrete subtest 2 个 variant，共 14 张。 |

Concrete subtests 是：

```text
raw_price unit_price brand flavor size price size_weight
```

## 2. Category 级具体假定

下列每个 category 中，`core` 只使用 variant 1；`full` / `all` 使用 variant 1 和 variant 2。`default_budget` 只用于 `budget` family 的阈值构造；`base_price` 是非 budget 任务和 basic rationality 的默认/回退货架价。

### 2.1 `tortilla_chips`

固定参数：

| field              | value                  |
| ------------------ | ---------------------- |
| category           | `TORTILLA CHIPS`     |
| csv                | `chips_sku_list.csv` |
| product term       | tortilla chips         |
| `default_budget` | `$3.00`              |
| `base_price`     | `$4.49`              |

实验假定：

| experiment            | variant 1                                                     | variant 2                                                                                                    | 具体假定                                                                   |
| --------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| `budget/raw_price`  | budget`$3.00` | budget `$3.50`                            | 8 个真实 SKU；随机 1 个目标位置，目标`price = base_price = budget - random_offset`，其他 SKU 高于 budget。 |                                                                            |
| `budget/unit_price` | unit budget`$3.00` | unit budget `$3.50`                  | 8 个有可解析`weight` 的真实 SKU；目标 `base_price / weight <= budget`，其他 SKU 高于 budget。            |                                                                            |
| `brand`             | Tostitos                                                      | Doritos                                                                                                      | 目标 brand 只出现一次；brand 从`item` / 包装图推断，不作为图上单独字段。 |
| `flavor`            | Restaurant Style                                              | Scoops                                                                                                       | 目标 flavor 只出现一次。                                                   |
| `size`              | larger than 8.5 oz bag                                        | smaller than 9.25 oz bag                                                                                     | 目标 SKU 是唯一满足大小阈值比较的商品；比较用`weight`。                  |
| `price`             | adjusted_low around`$4.49` | adjusted_high around `$4.49` | 同一 anchor SKU 复制 8 次，只改变价格；正确项为唯一最低价。                                                  |                                                                            |
| `size_weight`       | 7, 8.5, 9.25, 10, 11, 12, 13, 15 oz bag                       | variant 2 使用反向顺序后 shuffle                                                                             | 同一 anchor SKU、同价，只改变 size / weight；正确项为 15 oz bag。          |

`price` 的候选价格：

| variant       | price options before shuffle                                                           |
| ------------- | -------------------------------------------------------------------------------------- |
| adjusted_low  | `$4.46`, `$4.51`, `$4.53`, `$4.54`, `$4.55`, `$4.56`, `$4.57`, `$4.58` |
| adjusted_high | `$3.29`, `$3.94`, `$4.34`, `$4.74`, `$5.29`, `$5.64`, `$6.09`, `$6.59` |

### 2.2 `cold_cereal`

固定参数：

| field              | value                        |
| ------------------ | ---------------------------- |
| category           | `COLD CEREAL`              |
| csv                | `cold_cereal_sku_list.csv` |
| product term       | cold cereal                  |
| `default_budget` | `$3.50`                    |
| `base_price`     | `$4.99`                    |

实验假定：

| experiment            | variant 1                                                     | variant 2                                                                       | 具体假定                                                          |
| --------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `budget/raw_price`  | budget`$3.50` | budget `$4.00`                            | 8 个真实 SKU；唯一一个`base_price <= budget`。                                |                                                                   |
| `budget/unit_price` | unit budget`$3.50` | unit budget `$4.00`                  | 8 个有可解析`weight` 的真实 SKU；唯一一个 `base_price / weight <= budget`。 |                                                                   |
| `brand`             | General Mills                                                 | Kellogg's                                                                       | 目标 brand 只出现一次。                                           |
| `flavor`            | Original                                                      | Honey Nut                                                                       | 目标 flavor 只出现一次。                                          |
| `size`              | larger than 10.7 oz box                                       | smaller than 12 oz box                                                          | 目标 SKU 是唯一满足大小阈值比较的商品；比较用`weight`。         |
| `price`             | adjusted_low around`$4.99` | adjusted_high around `$4.99` | 同一 anchor SKU 复制 8 次，只改变价格；正确项为唯一最低价。                     |                                                                   |
| `size_weight`       | 8.9, 10.7, 12, 13.5, 14.8, 16, 18, 21 oz box                  | variant 2 使用反向顺序后 shuffle                                                | 同一 anchor SKU、同价，只改变 size / weight；正确项为 21 oz box。 |

`price` 的候选价格：

| variant       | price options before shuffle                                                           |
| ------------- | -------------------------------------------------------------------------------------- |
| adjusted_low  | `$4.96`, `$5.01`, `$5.03`, `$5.04`, `$5.05`, `$5.06`, `$5.07`, `$5.08` |
| adjusted_high | `$3.79`, `$4.44`, `$4.84`, `$5.24`, `$5.79`, `$6.14`, `$6.59`, `$7.09` |

### 2.3 `coffee`

固定参数：

| field              | value                   |
| ------------------ | ----------------------- |
| category           | `COFFEE`              |
| csv                | `coffee_sku_list.csv` |
| product term       | coffee                  |
| `default_budget` | `$7.00`               |
| `base_price`     | `$9.99`               |

实验假定：

| experiment            | variant 1                                                     | variant 2                                                                       | 具体假定                                                          |
| --------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `budget/raw_price`  | budget`$7.00` | budget `$7.50`                            | 8 个真实 SKU；唯一一个`base_price <= budget`。                                |                                                                   |
| `budget/unit_price` | unit budget`$7.00` | unit budget `$7.50`                  | 8 个有可解析`weight` 的真实 SKU；唯一一个 `base_price / weight <= budget`。 |                                                                   |
| `brand`             | Peet's                                                        | Starbucks                                                                       | 目标 brand 只出现一次。                                           |
| `flavor`            | French Roast                                                  | House Blend                                                                     | 目标 flavor 只出现一次。                                          |
| `size`              | larger than 10 oz bag                                         | smaller than 12 oz bag                                                          | 目标 SKU 是唯一满足大小阈值比较的商品；比较用`weight`。         |
| `price`             | adjusted_low around`$9.99` | adjusted_high around `$9.99` | 同一 anchor SKU 复制 8 次，只改变价格；正确项为唯一最低价。                     |                                                                   |
| `size_weight`       | 8, 10, 12, 14, 16, 18, 20, 24 oz bag                          | variant 2 使用反向顺序后 shuffle                                                | 同一 anchor SKU、同价，只改变 size / weight；正确项为 24 oz bag。 |

`price` 的候选价格：

| variant       | price options before shuffle                                                                  |
| ------------- | --------------------------------------------------------------------------------------------- |
| adjusted_low  | `$9.96`, `$10.01`, `$10.03`, `$10.04`, `$10.05`, `$10.06`, `$10.07`, `$10.08` |
| adjusted_high | `$8.79`, `$9.44`, `$9.84`, `$10.24`, `$10.79`, `$11.14`, `$11.59`, `$12.09`   |

### 2.4 `at_home_crackers`

固定参数：

| field              | value                     |
| ------------------ | ------------------------- |
| category           | `AT HOME CRACKERS`      |
| csv                | `crackers_sku_list.csv` |
| product term       | crackers                  |
| `default_budget` | `$3.00`                 |
| `base_price`     | `$4.29`                 |

实验假定：

| experiment            | variant 1                                                     | variant 2                                                                       | 具体假定                                                          |
| --------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `budget/raw_price`  | budget`$3.00` | budget `$3.50`                            | 8 个真实 SKU；唯一一个`base_price <= budget`。                                |                                                                   |
| `budget/unit_price` | unit budget`$3.00` | unit budget `$3.50`                  | 8 个有可解析`weight` 的真实 SKU；唯一一个 `base_price / weight <= budget`。 |                                                                   |
| `brand`             | Nabisco                                                       | Pepperidge Farm                                                                 | 目标 brand 只出现一次。                                           |
| `flavor`            | Wheat                                                         | Honey                                                                           | 目标 flavor 只出现一次。                                          |
| `size`              | larger than 7 oz box                                          | smaller than 8.8 oz box                                                         | 目标 SKU 是唯一满足大小阈值比较的商品；比较用`weight`。         |
| `price`             | adjusted_low around`$4.29` | adjusted_high around `$4.29` | 同一 anchor SKU 复制 8 次，只改变价格；正确项为唯一最低价。                     |                                                                   |
| `size_weight`       | 6, 7, 8, 8.8, 10, 12, 13.7, 16 oz box                         | variant 2 使用反向顺序后 shuffle                                                | 同一 anchor SKU、同价，只改变 size / weight；正确项为 16 oz box。 |

`price` 的候选价格：

| variant       | price options before shuffle                                                           |
| ------------- | -------------------------------------------------------------------------------------- |
| adjusted_low  | `$4.26`, `$4.31`, `$4.33`, `$4.34`, `$4.35`, `$4.36`, `$4.37`, `$4.38` |
| adjusted_high | `$3.09`, `$3.74`, `$4.14`, `$4.54`, `$5.09`, `$5.44`, `$5.89`, `$6.39` |

### 2.5 `carbonated_soft_drinks`

固定参数：

| field              | value                        |
| ------------------ | ---------------------------- |
| category           | `CARBONATED SOFT DRINKS`   |
| csv                | `soft_drinks_sku_list.csv` |
| product term       | carbonated soft drinks       |
| `default_budget` | `$4.00`                    |
| `base_price`     | `$5.99`                    |

实验假定：

| experiment            | variant 1                                                                                                     | variant 2                                                                       | 具体假定                                                           |
| --------------------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `budget/raw_price`  | budget`$4.00` | budget `$4.50`                                                                            | 8 个真实 SKU；唯一一个`base_price <= budget`。                                |                                                                    |
| `budget/unit_price` | unit budget`$4.00` | unit budget `$4.50`                                                                  | 8 个有可解析`weight` 的真实 SKU；唯一一个 `base_price / weight <= budget`。 |                                                                    |
| `brand`             | Coca-Cola                                                                                                     | Pepsi                                                                           | 目标 brand 只出现一次。                                            |
| `flavor`            | Cola                                                                                                          | Diet Cola                                                                       | 目标 flavor 只出现一次。                                           |
| `size`              | larger than 12 fl oz can                                                                                      | smaller than 20 fl oz bottle                                                    | 目标 SKU 是唯一满足大小阈值比较的商品；比较用`weight`。          |
| `price`             | adjusted_low around`$5.99` | adjusted_high around `$5.99`                                                 | 同一 anchor SKU 复制 8 次，只改变价格；正确项为唯一最低价。                     |                                                                    |
| `size_weight`       | 8 fl oz can, 12 fl oz can, 16 fl oz can, 20 fl oz bottle, 1 L bottle, 1.25 L bottle, 1.5 L bottle, 2 L bottle | variant 2 使用反向顺序后 shuffle                                                | 同一 anchor SKU、同价，只改变 size / weight；正确项为 2 L bottle。 |

`price` 的候选价格：

| variant       | price options before shuffle                                                           |
| ------------- | -------------------------------------------------------------------------------------- |
| adjusted_low  | `$5.96`, `$6.01`, `$6.03`, `$6.04`, `$6.05`, `$6.06`, `$6.07`, `$6.08` |
| adjusted_high | `$4.79`, `$5.44`, `$5.84`, `$6.24`, `$6.79`, `$7.14`, `$7.59`, `$8.09` |

## 3. 评分入口

AI 只看到 `screen_file` 图片和 `prompt_instruction`，不看到 `correct_sku_id`, `correct_product_number`, `skus` 或 scoring rule。推荐 AI 返回：

```json
{
  "row": 1,
  "col": 3,
  "confidence": 0.72,
  "reason": "optional short reason"
}
```

评分时用：

```text
chosen_product_number = (row - 1) * 4 + col
```

再从 `request_file.skus` 映射回被选 SKU。主指标仍分开报告 instruction following 和 basic rationality；`budget_accuracy` 是 `raw_price` 与 `unit_price` 的 macro average。
