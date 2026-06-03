# generate_image

这个工作区专门用于纯 LLM 货架图工作流。

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
- `Sponsored`
- `Overall Pick`
- `Only X Remaining`

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

```bash
python openrouter_shelf_image.py \
  --mode generate \
  --category "TORTILLA CHIPS" \
  --sample-size 8 \
  --sample-count 1 \
  --request-output-file output/generate_request.json \
  --output-file output/shelf.png
```

测试脚本会真实调用 OpenRouter，需要设置 `OPENROUTER_API_KEY`：

```bash
python test_generate_image_mode.py
```

## 改图模式

改图 attribute 随机生成逻辑：

- Position：随机打乱 8 个商品位置。
- Sponsored Tag：随机给 `X` 个 listing 加 Sponsored，`X ~ Unif({1,2,3,4})`。
- Overall Pick Tag：随机给一个无 Sponsored 的 listing 加 Overall Pick。
- Scarcity Tag：随机给一个无 Sponsored/Overall Pick 的 listing 加 `Only X Remaining`，`X ~ Unif({1,2,3,4,5})`。
- Price：`p'_j = p_j * f_j`，`f_j ~ logNormal(mu=0, sigma=0.3)`。
- Size：按具体品类生成，例如 chips 为常见重量，饮料为容量，coffee/cereal/ice cream/yogurt/crackers/dips 等有各自常见规格。

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
