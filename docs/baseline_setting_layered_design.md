# Baseline Setting 实验设计

本文档用论文方法部分的写法描述 Baseline Setting，同时保留可复现的具体做法。这里把 **instruction following** 和 **basic rationality** 分开写，因为两类实验使用的图片结构、操纵变量、prompt 和评分规则都不同。

## 1. 总体目标

Baseline Setting 构造一组视觉购物选择任务，用来评估 AI 在货架图中选择商品的能力。每个样本是一张 2x4 货架图，共 8 个可选商品。被测 AI 只看到图片和 shopper instruction，并返回所选商品的位置。

实验分成两组：

- **Instruction following**：图片中有 8 个不同真实 SKU。prompt 给出一个明确约束，例如预算、品牌、口味或规格大小，AI 需要选择唯一满足约束的商品。
- **Basic rationality**：图片中 8 个 option 来自同一个 anchor SKU。商品身份保持不变，只改变价格或规格，AI 需要选择理性上占优的 option。

所有实验都使用 edit-only 图片生成方式：先提供一张统一 baseline shelf image，再基于这张图改出不同任务图片。这样可以固定货架布局、相机角度和整体视觉风格，使实验差异主要来自 tag 上的决策变量。

## 2. 共同视觉约束

所有 Baseline Setting 图片都满足以下视觉约束：

- 图片布局固定为 2 行 x 4 列，共 8 个 focal products。
- 每个 cell 只显示 1 个 focal product，不用库存、堆叠、空位或 facings 表达实验变量。
- 每个商品正下方有一个真实超市 shelf rail 风格的纸质 tag。
- tag 使用固定 5 行格式：白色纸质 tag，黑色水平文字，位于每个商品正下方并居中贴在 shelf rail 上。
- tag 的行顺序固定为：Line 1 centered item/name；Line 2 centered price（两位小数且最突出）；Line 3 centered category_name；Line 4 centered flavor；Line 5 centered size。
- 图片中不显示 shopper instruction、task title、解释文字、SKU ID、row/column 编号、`product_number`、库存、rating、review、promotion sticker 或 bestseller badge。
- `product_number` 只在 manifest / scoring 中由 8 个 SKU 的顺序派生，不出现在图片中。

位置映射固定为：

```text
product_number = (row - 1) * 4 + col
```

因此 row 1 col 1 到 row 2 col 4 分别对应内部选项 1 到 8。

## 3. Instruction Following Setup

### 3.1 图片和变量

Instruction following 使用 **assortment baseline**。每张图包含 8 个不同真实 SKU，且每个 SKU 都有商品参考图。SKU 顺序在构造后被 shuffle，并映射到 2x4 货架位置。

该 setup 中有四个 top-level task family：

```text
budget brand flavor size
```

其中 `budget` family 不单独生成 `budget` subtest，而是包含两个子实验：

```text
raw_price unit_price
```

因此 instruction following 的 concrete subtests 是：

```text
raw_price unit_price brand flavor size
```

### 3.2 Prompt 形式

每个样本的 shopper instruction 只描述要满足的选择约束，不提供答案、不提供 SKU 顺序，也不提供评分规则。

| subtest | prompt 语义 |
| --- | --- |
| `raw_price` | Choose the product with raw shelf price at or below `$B`. |
| `unit_price` | Choose the product with unit price at or below `$B`; unit price is raw price divided by weight. |
| `brand` | Choose the product from brand `<target_brand>`. |
| `flavor` | Choose the product with `<target_flavor>` flavor. |
| `size` | Choose the product with size larger than / smaller than `<target_size>`. |

这里 `$B` 是 budget threshold。对 `raw_price`，它表示货架总价预算；对 `unit_price`，它表示单位价预算。

### 3.3 `raw_price` 构造

`raw_price` 检验 AI 是否能按照货架总价预算选择商品。每个样本先选出 8 个真实 SKU 并打乱位置，然后从最终 8 个位置中随机抽取 1 个目标位置。

第 `variant` 个样本的预算为：

```text
budget = default_budget + 0.50 * variant
```

目标商品的价格设置为：

```text
price = base_price = budget - random_offset
random_offset 从 [0, budget) 中随机抽取
```

其他 7 个商品的价格设置为：

```text
price = base_price = budget + random_offset
random_offset 从 [0.05, 1.80] 中抽取
7 个非目标 offset 唯一，并在非目标商品之间打乱分配
```

因此正确答案是唯一满足下式的 SKU：

```text
base_price <= budget
```

### 3.4 `unit_price` 构造

`unit_price` 检验 AI 是否能按照单位价预算选择商品。样本只使用有可解析正 `weight` 的 SKU。构造流程与 `raw_price` 相同，但价格操纵先发生在单位价上。

目标商品的单位价为：

```text
unit_price = budget - random_offset
```

非目标商品的单位价为：

```text
unit_price = budget + random_offset
```

随后写入货架价：

```text
price = base_price = round(unit_price * weight, 2)
```

因此正确答案是唯一满足下式的 SKU：

```text
base_price / weight <= budget
```

注意：这个子实验中，最终货架总价 `price` 可以大于 budget，因为 budget 是单位价预算，不是总价预算。

### 3.5 `brand` 构造

`brand` 检验 AI 是否能遵循目标品牌偏好。每个样本选择 1 个目标品牌 SKU 和 7 个非目标品牌 SKU，再打乱位置。

品牌不作为单独 tag 字段展示，而是从 `item` 文本和商品包装中推断。正确答案是唯一满足：

```text
infer_brand(dataset, item) == target_brand
```

该任务不做人为价格变化。每个 SKU 使用数据中的原始价格；如果数据价格不可解析，则回退到该 category 的默认 `base_price`。

### 3.6 `flavor` 构造

`flavor` 检验 AI 是否能遵循目标口味偏好。每个样本选择 1 个目标 flavor SKU 和 7 个非目标 flavor SKU，再打乱位置。

正确答案是唯一满足：

```text
flavor == target_flavor
```

该任务不做人为价格变化，价格规则与 `brand` 相同。

### 3.7 `size` 构造

`size` 检验 AI 是否能理解规格大小比较，而不是简单匹配某个 size 文本。每个样本只使用有可解析正 `weight` 的 SKU。

任务有两种关系：

```text
greater_than: 选择 size 大于 target size 的商品
less_than:    选择 size 小于 target size 的商品
```

`variant` 为偶数时使用 `greater_than`，为奇数时使用 `less_than`。每个样本选择 1 个满足比较关系的目标 SKU 和 7 个不满足比较关系的非目标 SKU，再打乱位置。

实际评分时不直接比较字符串，而是把 size 解析为 `weight`：

```text
greater_than: weight > target_weight
less_than:    weight < target_weight
```

该任务不做人为价格变化。

### 3.8 Category 级取值

下表给出 instruction following 中各 category 的具体目标值。`core` 只使用 variant 1；`full` / `all` 使用 variant 1 和 variant 2。

| category | raw price budget | unit price budget | brand targets | flavor targets | size targets |
| --- | --- | --- | --- | --- | --- |
| tortilla chips | `$3.00`, `$3.50` | `$3.00`, `$3.50` | Tostitos; Doritos | Restaurant Style; Scoops | larger than 8.5 oz bag; smaller than 9.25 oz bag |
| cold cereal | `$3.50`, `$4.00` | `$3.50`, `$4.00` | General Mills; Kellogg's | Original; Honey Nut | larger than 10.7 oz box; smaller than 12 oz box |
| coffee | `$7.00`, `$7.50` | `$7.00`, `$7.50` | Peet's; Starbucks | French Roast; House Blend | larger than 10 oz bag; smaller than 12 oz bag |
| at-home crackers | `$3.00`, `$3.50` | `$3.00`, `$3.50` | Nabisco; Pepperidge Farm | Wheat; Honey | larger than 7 oz box; smaller than 8.8 oz box |
| carbonated soft drinks | `$4.00`, `$4.50` | `$4.00`, `$4.50` | Coca-Cola; Pepsi | Cola; Diet Cola | larger than 12 fl oz can; smaller than 20 fl oz bottle |

## 4. Basic Rationality Setup

### 4.1 图片和变量

Basic rationality 使用 **identical option baseline**。每张图先选定一个 anchor SKU，然后复制成 8 个 option。8 个 option 在商品身份上相同，因此不应该引入品牌、包装、口味或商品类型偏好。实验只操纵一个理性比较变量：

```text
price
size / weight
```

该 setup 包含两个 concrete subtests：

```text
price size_weight
```

### 4.2 Prompt 形式

| subtest | prompt 语义 |
| --- | --- |
| `price` | Choose the lowest-priced option. The products are otherwise identical. |
| `size_weight` | Choose the option with the largest weight. The options have the same price. |

这两个任务不是 preference following。它们不要求 AI 根据品牌、口味或用户偏好做选择，而是检查 AI 是否避免选择被支配的 option。

### 4.3 `price` 构造

`price` 任务中，8 个 option 来自同一个 anchor SKU，商品图、item、flavor、size 和 weight 保持不变，只改变价格。

`core` 使用小幅价格差异：

```text
base - 0.03
base + 0.02
base + 0.04
base + 0.05
base + 0.06
base + 0.07
base + 0.08
base + 0.09
```

`full` / `all` 额外使用大幅价格差异：

```text
base - 1.20
base - 0.55
base - 0.15
base + 0.25
base + 0.80
base + 1.15
base + 1.60
base + 2.10
```

价格列表在写入 8 个位置前会 shuffle。正确答案是唯一满足：

```text
price == min(price_1, ..., price_8)
```

### 4.4 `size_weight` 构造

`size_weight` 任务中，8 个 option 来自同一个 anchor SKU，所有 option 的价格完全相同，只改变 `size` 和由 size 解析出的 `weight`。

正确答案是唯一满足：

```text
weight == max(weight_1, ..., weight_8)
```

`variant 1` 使用 category 的 size list 原始顺序后 shuffle；`variant 2` 先反转 size list，再 shuffle。

### 4.5 Category 级取值

下表给出 basic rationality 中各 category 的默认价格和 size candidate。`price` 任务围绕 `base_price` 生成小幅或大幅价格差异；`size_weight` 任务使用对应的 size candidate，并以其中最大 weight 为正确答案。

| category | base price | `size_weight` candidates | correct size |
| --- | ---: | --- | --- |
| tortilla chips | `$4.49` | 7, 8.5, 9.25, 10, 11, 12, 13, 15 oz bag | 15 oz bag |
| cold cereal | `$4.99` | 8.9, 10.7, 12, 13.5, 14.8, 16, 18, 21 oz box | 21 oz box |
| coffee | `$9.99` | 8, 10, 12, 14, 16, 18, 20, 24 oz bag | 24 oz bag |
| at-home crackers | `$4.29` | 6, 7, 8, 8.8, 10, 12, 13.7, 16 oz box | 16 oz box |
| carbonated soft drinks | `$5.99` | 8 fl oz can, 12 fl oz can, 16 fl oz can, 20 fl oz bottle, 1 L bottle, 1.25 L bottle, 1.5 L bottle, 2 L bottle | 2 L bottle |

## 5. 评估方式

对每个样本，被测 AI 只看到：

```text
screen_file 图片
prompt_instruction
固定回答格式说明
```

AI 不看到 `correct_sku_id`、`correct_product_number`、完整 `skus` 或 scoring rule。推荐输出格式为：

```json
{
  "row": 1,
  "col": 3,
  "confidence": 0.72,
  "reason": "optional short reason"
}
```

评分脚本将 `row` 和 `col` 映射到内部 option 顺序：

```text
chosen_product_number = (row - 1) * 4 + col
```

再从 `request_file.skus` 中取出被选 SKU，并与 manifest 中的正确答案比较。

主结果分开报告：

- `instruction_following_accuracy`: `budget_accuracy`, `brand_accuracy`, `flavor_accuracy`, `size_accuracy` 的 macro average。其中 `budget_accuracy` 是 `raw_price_accuracy` 和 `unit_price_accuracy` 的 macro average。
- `basic_rationality_accuracy`: `price_accuracy` 和 `size_weight_accuracy` 的 macro average。

同时单独报告无效回答率和图片 QA 失败率，以区分模型选择错误、回答格式错误和图片刺激不可用。
