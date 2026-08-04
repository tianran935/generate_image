z

# 最低能力测试：全局参数与执行口径

当前 minimum-capability 实验分两组：

1. Instruction following, 多个真实 SKU：`budget`, `brand`, `flavor`, `size`, `raw_price`, `unit_price`
2. Basic rationality, 单个 SKU 复制为 8 个 option：`price`, `size_weight`

`color`, `rating`, `reviews`, `number_of_reviews`, `inventory_remaining` 不作为当前 request SKU 字段，也不作为最低能力测试场景。

## 1. Request SKU 字段白名单

每个 request 的 `skus` 只能包含下列字段：

| SKU 字段             | 来源/规则                                  | 图上含义                         |
| -------------------- | ------------------------------------------ | -------------------------------- |
| `sku_id`           | CSV`upc_id`，单 SKU rationality 可加后缀 | 商品身份                         |
| `item`             | CSV`upc_description`                     | 商品名/包装识别线索              |
| `category_name`    | CSV 或 dataset config                      | 品类                             |
| `base_price`       | 原始价格；正式场景中显式写死               | raw price                        |
| `price`            | 货架价格；默认等于`base_price`           | shelf price                      |
| `promotion`        | 固定`none`                               | 促销标识，本阶段不显示           |
| `bestseller_badge` | 固定`none`                               | 热卖 badge，本阶段不显示         |
| `size`             | 品类规格规则或 rationality size vector     | 包装规格                         |
| `flavor`           | 商品名规则推断                             | 口味/款式                        |
| `weight`           | 从`size` 解析出的数值                    | unit price/size rationality 计算 |
| `position`         | 2x4 固定顺序                               | 货架位置                         |
| `product_image`    | `pic_reference/` 按 UPC/rank 匹配        | 包装参考图                       |

`product_number` 不写入 SKU；manifest 中的 `correct_product_number` 从 `skus` 列表顺序派生。

## 2. 固定视觉参数

- layout: 2 rows x 4 columns, exactly 8 focal products.
- 每个 cell 只显示 1 个 focal product，不用库存、空位、堆叠、重复 facings 表达变量。
- 主货架 tag 位于每个商品正下方，贴在 shelf rail 上，样式参考真实超市纸质价签。
- 主货架 tag 显示：`price`, `category_name`, `item`, `flavor`, `size`。
- shopper instruction 只写入 request/manifest，不出现在图片中。
- `promotion=none`, `bestseller_badge=none`；正式最低能力图不显示 sale/promo/bestseller sticker。

推荐生图命令：

```bash
python generate_image/openrouter_shelf_image.py \
  --request-file <request.json> \
  --output-file <screen.png> \
  --reference-sheet-only \
  --aspect-ratio 4:3 \
  --image-size 1K
```

## 3. 市场份额实验

第二部分 market-share choice 实验当前先启用 `tortilla_chips`，全部使用 edit mode。原图固定参考：

```text
/Users/tianran/Desktop/research/profLin/选品/generate_image/output/runs/原始参考.png
```

### 3.1 参数随机方式

- `item`: 通过 `generate_image/core/shelf_sampling.py` 从 `TORTILLA CHIPS` SKU 池随机抽 8 个，并过滤到能匹配商品参考图的 SKU。
- `position`: 复用 `positions_2x4()` 的 8 个固定 cell，再在 `build_edit_payload()` / `perturb_edit_attributes()` 中随机打乱。
- `price`: 以 `base_price * logNormal(0, 0.3)` 随机，并用 `$x.xx` 两位小数格式显示。
- `size`: 复用 `shelf_sampling.infer_size()` 或已有 SKU size。
- `promotion`: 每张图随机 1-4 个 SKU 设为 `Promotion`，其余为 `none`。
- `bestseller_badge`: 每张图随机 1-4 个 SKU 设为短文案，如 `BEST SELLER`、`TOP PICK`、`HOT`，其余为 `none`。
- `promotion` 和 `bestseller_badge` 独立随机，允许落在同一个 SKU 上。

市场份额实验不设置 `correct_sku_id`；manifest 只记录 8 个 option、随机化参数和 shopper instruction。

### 3.2 Sticker tag 规则

`promotion` 和 `bestseller_badge` 不放入主货架 tag，而是用额外夹在货架 rail 上的真实超市 shelf talker / Club Price 吊牌表示。

共同要求：

- 看起来像后来夹到货架 rail 上的促销吊牌、Club Price 牌、货架贴条，而不是主价签的一部分。
- 必须先保留完整主货架 tag，再额外贴 sticker；sticker 不能替代主价签中的任意一行、色带或内容区。
- 优先夹在主货架 tag 前方、下方或旁边的 rail 上，像 Safeway 货架上的黄色 Club Price 吊牌。
- 不使用卡通徽章、爆炸贴、浮动 icon、app UI 样式标签。
- 不贴在商品包装主体上；如必须靠近包装，只能靠在不遮挡 logo 的角落且仍像货架 rail signage。
- 不得遮挡 product number 和 price。
- 不得遮挡主价签上的 item、category、flavor、size 等正文。
- 不得遮挡商品品牌 logo 的主体区域。
- 每个 sticker 只服务一个商品，不能跨 cell。
- 不得把 sticker 画成 price 下方同一个价签矩形内的彩色行。
- 标签必须和商品一一对应。
- 标签不重叠、不跨格、不遮挡包装主体。
- 标签文字黑色、高对比、水平排列。
- 不在图片顶部写任务说明。
- 不在图片中写 `Choose ...` 这类 shopper instruction。
- shopper instruction 只放在 agent prompt 和 manifest 中。
- 不能把所有字段画成一个大表格；必须像真实货架上一格一个价签。

`promotion` sticker:

- 颜色：橙色、红色或黄色高亮底。
- 形状：真实货架促销牌，优先为夹在 rail 上并向下垂的矩形纸牌，或窄条 shelf talker。
- 文案示例：`PROMO`、`SALE`、`Club Price`。
- 若字段为 `Promotion`，必须出现 promotion sticker。
- 若字段为 `none`，不得出现 promotion sticker。

`bestseller_badge` sticker:

- 颜色：蓝色、金色或红色高亮底。
- 形状：克制的货架 rail 小贴条、侧边 tab 或夹上去的小矩形纸牌；不要用卡通徽章或爆炸贴。
- 文案示例：`BEST SELLER`、`TOP PICK`、`HOT`。
- 若字段非 `none`，必须用字段给定文案或等价短文案显示。
- 若字段为 `none`，不得出现 bestseller sticker。

最低能力测试当前不启用 promotion/bestseller，因此正式图中不应出现这些新贴 sticker。

## 4. 场景定义

`core` 每个 dataset 每个 subtest 1 张；`full` / `all` 每个 dataset 每个 subtest 2 张。

Instruction following:

- `budget`: 8 个不同 SKU，只有 1 个 SKU 的 `price <= target budget`。
- `brand`: 8 个不同 SKU，目标品牌只出现 1 次；brand 从 `item`/包装图推断，不作为 SKU 字段。
- `flavor`: 8 个不同 SKU，只有 1 个 SKU 的 `flavor == target flavor`。
- `size`: 8 个不同 SKU，只有 1 个 SKU 的 `size > target size` 或 `size < target size`；比较时使用从 size 解析出的 `weight`。
- `raw_price`: 8 个不同 SKU，正确答案为 `base_price` 最低的 SKU。
- `unit_price`: 8 个不同 SKU，且每个 SKU 都有可解析 `weight`；正确答案为 `base_price / weight` 最低的 SKU。

Basic rationality:

- `price`: 同一个 anchor SKU 复制为 8 个 option，包装、flavor、size、weight 固定，只上下调整 `price`；正确答案为 `price` 最低。
- `size_weight`: 同一个 anchor SKU 复制为 8 个 option，`price` 固定，只改变 `size` 和 `weight`；正确答案为 `weight` 最大。

## 5. 校验标准

每个 request 生成前必须满足：

- `skus` 数量为 8。
- 每个 SKU 字段精确等于白名单。
- 不包含 `color`, `rating`, `reviews`, `number_of_reviews`, `inventory_remaining`。
- `position` 固定为 row 1 col 1-4、row 2 col 1-4。
- 每个场景只有 1 个正确答案。
- `unit_price` winner 等于 `min(base_price / weight)`。
- `size_weight` winner 等于最大 `weight`，且 8 个 option 的 `price` 完全相同。
