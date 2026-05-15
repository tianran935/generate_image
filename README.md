# Part B Shelf Image Generator MVP

这是一个与上游 LLM 选择流程独立的 `Part B` 图片生成工作流。目标是：

- 输入一组 SKU，自动生成货架图
- 支持基础位置控制：上下、左右
- 一次性建立素材库
- 后续每张刺激图都由 `Python + PIL` 确定性合成
- 支持批量生成 PNG 实验图片

## 目录

- `generate_asset_library.py`
  一次性生成素材库，包括：
  - 干净货架背景
  - 普通价签模板
  - 促销价签模板
  - 划线价模板
  - 基础标识元素
- `render_shelf_batch.py`
  读取 SKU catalog 和 scenario 配置，批量输出货架 PNG。
- `sample_catalog.json`
  SKU 样例 catalog。每个 SKU 可绑定真实产品图路径；若缺失，则使用确定性占位包装图。
- `sample_scenarios.json`
  批量场景样例，展示不同 SKU 的上下左右位置变化。
- `output/`
  生成结果目录。

## 输入 schema

### catalog

每个 SKU 至少包含：

```json
{
  "sku_id": "cereal_001",
  "name": "Cheerios Original",
  "brand": "General Mills",
  "category": "cold cereal",
  "size": "18 oz",
  "price": 4.79,
  "image_path": "optional/local/path.png"
}
```

### scenario

每个 scenario 至少包含：

```json
{
  "scenario_id": "scene_001",
  "title": "top_vs_bottom_demo",
  "placements": [
    {
      "sku_id": "cereal_001",
      "row": 1,
      "col": 1
    },
    {
      "sku_id": "cereal_002",
      "row": 2,
      "col": 2
    }
  ]
}
```

说明：

- `row` 控制上下位置，1 是上层
- `col` 控制左右位置，1 是最左
- 可选 `offset_x`、`offset_y` 做细微偏移
- 可选 `price_style` 使用 `regular` / `sale` / `markdown`

## 运行

先生成素材库：

```bash
python3 part_b_mvp/generate_asset_library.py
```

再批量生成场景：

```bash
python3 part_b_mvp/render_shelf_batch.py \
  --catalog-file part_b_mvp/sample_catalog.json \
  --scenario-file part_b_mvp/sample_scenarios.json \
  --output-dir part_b_mvp/output/generated_shelves
```

## 设计原则

- 每张图由固定背景 + 固定模板 + 固定坐标合成
- 同一输入总是生成相同输出
- 不在每个刺激的生成过程中调用 LLM
- 先保证结构正确和可识别，再逐步扩展到 facings、标签、更多实验变量
