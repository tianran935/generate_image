# generate_image

这个工作区专门用于纯 LLM 货架图工作流。

## 目录速查

- `openrouter_shelf_image.py`：主入口；负责生图、改图、商品参考图拼接、OpenRouter 调用。
- `shelf_sampling.py`：从 SKU 表中按品类抽样，并构造基础货架 payload。
- `build_edit_request.py`：根据已有货架图和基础请求构造改图请求。
- `test_generate_image_mode.py`：真实调用 OpenRouter 的生图验证脚本。
- `test_price_only_edit_mode.py`：真实调用 OpenRouter 的 price-only 改图验证脚本。
- `output/`：生成结果目录；已按日期和 `生图` / `改图` 命名。

`output/` 文件命名约定：

- 主图：`YYYYMMDD_HHMMSS_生图_场景名.png` 或 `YYYYMMDD_HHMMSS_改图_场景名.png`
- 商品参考图：`YYYYMMDD_HHMMSS_生图_场景名_商品参考.png`
- 请求文件：`YYYYMMDD_HHMMSS_生图_场景名_请求.json`
- 改图源请求：`YYYYMMDD_HHMMSS_改图_场景名_源请求.json`

当前主脚本：

- `openrouter_shelf_image.py`
- `shelf_sampling.py`
- `build_edit_request.py`
- `test_generate_image_mode.py`

能力：

- `generate`：根据结构化货架特征直接生图
- `edit`：输入已有货架图，在尽量保持其他特征不变的前提下改图

默认模型：

- `openai/gpt-5.4-image-2`

支持的核心特征：

- `item`
- `price`
- `promotion`
- `position`
- `size`

## 采样接口

数据源默认使用：

- `../data_clean/top_50_skus_selected_categories.csv`

输入：

- `--category`：类别；可重复传入或逗号分隔。默认所有类别。
- `--sample-size`：每个类别采样数量，默认 `8`。
- `--sample-count`：每个类别采样次数，默认 `1`。

输出：

- 被选中样本的全部 CSV 字段。

示例：

```bash
python shelf_sampling.py \
  --category "TORTILLA CHIPS" \
  --sample-size 8 \
  --sample-count 1 \
  --output-file output/sample.json
```

## 生图模式

主程序可直接从 CSV 采样生成 2x4 货架：

默认会从 `../pic/images` 读取商品参考图。文件名可以包含 `rankXX` 和 UPC，例如 `rank01_028400009324.jpg`。程序会用 UPC 前缀和品类内 rank 自动匹配 SKU 图片；按品类采样时，会先过滤到有商品图的 SKU，再抽 8 个。若某个 SKU 找不到商品图，程序默认报错，避免模型只根据文字编造包装。

提示词会要求模型把商品参考图作为包装身份、品牌、颜色、logo、形状和正面 artwork 的主要依据。即使商品名是 POS 缩写，也应根据参考图还原真实商品包装，而不是生成泛化或虚构包装。同时包装形态和视觉大小需要与 `size` 字段一致，例如袋装重量、饮料容量、盒装规格、罐/瓶/杯/桶/多包装数量等。

每次调用图片模型前，程序会用 PIL 自动生成一张 2x4 商品参考缩略图，保存在输出图片旁边。例如 `output/shelf.png` 会对应生成 `output/shelf_商品参考.png`，用于检查本次抽样的 8 张商品图、价格和规格。这张 2x4 参考图也会作为额外输入传给图片模型，作为商品位置和相对包装大小的 layout guide。

```bash
python openrouter_shelf_image.py \
  --mode generate \
  --category "TORTILLA CHIPS" \
  --sample-size 8 \
  --sample-count 1 \
  --request-output-file output/generate_request.json \
  --output-file output/shelf.png
```

如需显式指定商品图目录：

```bash
python openrouter_shelf_image.py \
  --mode generate \
  --category "TORTILLA CHIPS" \
  --product-image-dir ../pic/images \
  --request-output-file output/generate_request.json \
  --output-file output/shelf.png
```

测试脚本会真实调用 OpenRouter，需要设置 `OPENROUTER_API_KEY`：

```bash
python test_generate_image_mode.py
```

## 改图模式

改图 attribute 随机生成逻辑：

- Price：`p'_j = p_j * f_j`，`f_j ~ logNormal(mu=0, sigma=0.3)`。

改图模式下，生图和改图之间只有 `price` 不同。SKU、位置、促销、size、商品参考图和包装外观都保持不变。
改图提示词同样要求所有商品保持真实商品身份，并让包装大小和 `size` 字段对齐。
改图时会同时输入原货架图和 8 张商品参考图：原货架图用于保持整体货架环境，商品参考图用于约束每个 SKU 的真实包装，不允许模型换成自编商品。
改图也会生成对应的 2x4 商品参考缩略图，按同一位置排列，仅价格发生变化。

先构造改图请求：

```bash
python build_edit_request.py \
  --input-image output/shelf.png \
  --category "TORTILLA CHIPS" \
  --output-file output/edit_request.json
```

也可以直接让主程序采样并改图：

```bash
python openrouter_shelf_image.py \
  --mode edit \
  --input-image output/shelf.png \
  --base-request-file output/generate_request.json \
  --category "TORTILLA CHIPS" \
  --request-output-file output/edit_request.json \
  --output-file output/shelf_edit.png
```

运行示例：

```bash
python openrouter_shelf_image.py \
  --request-file sample_shelf_generate.json \
  --output-file output/shelf.png
```
