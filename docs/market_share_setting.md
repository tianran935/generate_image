
## 市场份额实验

第二部分 market-share choice 实验当前先启用 `tortilla_chips`，全部使用 edit mode。原图固定参考：

```text
/Users/tianran/Desktop/research/profLin/选品/generate_image/output/runs/原始参考.png
```

### 1 参数随机方式

- `item`: 通过 `generate_image/core/shelf_sampling.py` 从 `TORTILLA CHIPS` SKU 池随机抽 8 个，并过滤到能匹配商品参考图的 SKU。
- `position`: 复用 `positions_2x4()` 的 8 个固定 cell，再在 `build_edit_payload()` / `perturb_edit_attributes()` 中随机打乱。
- `price`: 以 `base_price * logNormal(0, 0.3)` 随机，并用 `$x.xx` 两位小数格式显示。
- `size`: 复用 `shelf_sampling.infer_size()` 或已有 SKU size。
- `promotion`: 每张图随机 1-4 个 SKU 设为 `Promotion`，其余为 `none`。
- `bestseller_badge`: 每张图随机 1-4 个 SKU 设为短文案，如 `BEST SELLER`、`TOP PICK`、`HOT`，其余为 `none`。
- `promotion` 和 `bestseller_badge` 独立随机，允许落在同一个 SKU 上。

市场份额实验不设置 `correct_sku_id`；manifest 只记录 8 个 option、随机化参数和 shopper instruction。

### 2 Sticker tag 规则

`promotion` 和 `bestseller_badge` 不放入主货架 tag，而是用额外夹在货架 rail 上的真实超市 shelf talker / Club Price 吊牌表示。

共同要求：

- 看起来像后来夹到货架 rail 上的促销吊牌、Club Price 牌、货架贴条，而不是主价签的一部分。
- 必须先保留完整主货架 tag，再额外贴 sticker；sticker 不能替代主价签中的任意一行、色带或内容区。
- 优先夹在主货架 tag 前方、下方或旁边的 rail 上，像 Safeway 货架上的黄色 Club Price 吊牌。
- 不使用卡通徽章、爆炸贴、浮动 icon、app UI 样式标签。
- 不贴在商品包装主体上；如必须靠近包装，只能靠在不遮挡 logo 的角落且仍像货架 rail signage。
- 不得遮挡 price。
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
