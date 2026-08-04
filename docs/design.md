# Baseline Setting 标签设计规范

本文档记录 Baseline Setting 正式图片中的主 shelf tag 规范。该规范只适用于 Baseline Setting，不覆盖 market-share 实验中的 promotion / bestseller shelf talker。

## 主 Shelf Tag

每个 focal product 正下方必须有且只有一个主 shelf tag。tag 需要像真实超市 shelf rail 上的白色纸质价签，而不是网页卡片、按钮、表格或浮动 UI。

固定格式：

```text
material: white paper shelf tag
placement: directly below each product, centered on shelf rail
text color: black
layout: fixed multiline tag
```

5 行内容顺序必须固定：

```text
Line 1 centered: item/name
Line 2 centered: price, two decimals, most visually prominent
Line 3 centered: category_name
Line 4 centered: flavor
Line 5 centered: size
```

所有字段值都来自 request 中对应 SKU 的结构化字段。不得省略、重排、改写、翻译、四舍五入或用其他文案替换字段值。

## 禁止内容

主 shelf tag、商品包装、贴纸或图片任何位置都不得出现：

```text
shopper instruction
task title
SKU ID
row/column number
product_number
rating/review
inventory
promotion/bestseller sticker
```

`product_number` 只作为 manifest / scoring 内部编号，由 8 个 SKU 的顺序派生，不写入 SKU，也不显示在图中。

## 与实验变量的关系

Baseline Setting 中，主 tag 是 AI 读取决策变量的主要视觉入口。所有任务都使用同一套 5 行 tag 格式：

- Instruction following: `raw_price`, `unit_price`, `brand`, `flavor`, `size`
- Basic rationality: `price`, `size_weight`

其中 `price` 必须始终保留两位小数；`item`, `category_name`, `flavor`, `size` 必须清晰可读。图片 QA 时应检查 tag 是否齐全、字段是否可读、是否没有 forbidden text。
