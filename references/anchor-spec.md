# 锚点规范 / Anchor specification

## 目的

一条笔记如果不能回到原文的确切位置，就无法被复核。锚点是"笔记 → 原文"的唯一通道，
因此它必须**小到能定位、大到能判定**：给一个页码太笼统，给整段正文又无法比对。

## 结构

```json
{
  "id": "A0012",
  "pid": "p4_12",
  "page": 4,
  "section": "S09",
  "sentence": 0,
  "kind": "text",
  "quote": "…逐字引文…",
  "truncated": false,
  "bbox": [72.0, 483.6, 290.3, 494.5],
  "char_offset": null,
  "origin": "extractive",
  "verified": true,
  "verify_method": "bbox_clip"
}
```

| 字段 | 约束 |
| --- | --- |
| `pid` | `p<page>_<n>`，同一份 `extract.json` 内唯一、可复查 |
| `page` | 1 起算，与 PDF 阅读器页码一致 |
| `sentence` | 段落内句子序号；`null` 表示整段引文 |
| `quote` | **逐字**子串，≤220 字符；截断时 `truncated=true` 且不加省略号（省略号会破坏匹配） |
| `bbox` | `[x0,y0,x1,y1]`，PDF 点（72 dpi）；`pdftotext`/OCR 层级为 `null` |
| `kind` | `text` / `table` / `figure` / `caption` / `paraphrase` |
| `origin` | `extractive`（脚本抽取）/ `judgment`（精修带入的 evidence） |

## 核验

核验**不使用**抽取管线自己的段落文本，按三级降序进行：

1. `bbox_clip`：重新打开 PDF，在 `bbox` 矩形内 `get_text("text", clip=rect)`，
   归一化后判断 `quote` 是否为子串。矩形错位或引文跨栏时会失败。
2. `page_text`：整页文本包含比对。矩形不可用或 clip 失败时使用。
3. `native_search`：用引文前 60 字符调 `page.search_for()`，兜住字形连写导致的差异。

归一化 `verify_key()`：NFKC → 去软连字符 → 去行尾断词 `-\s+` → 去全部空白 → 小写。
因此"换行位置不同""行尾连字符不同"不影响判定，**但改词一定会被判失败**。

## 判定与降级

| 情况 | 结果 |
| --- | --- |
| 三级中任一命中 | `verified=true`，记录实际命中方式 |
| 全部未命中 | `verified=false`，`result.status` 至少为 `partial`，写入 `uncertainty.anchor_failures` |
| 引文为空 | 直接判失败（不允许空引文充当证据） |

**禁止**人工把 `verified` 改为 `true`；失败通常意味着跨栏切断或页码错位，应回到
`extract.json` 检查该 `pid` 的 `bbox`，修正抽取后重跑。

## 精度预期

| 抽取层级 | 锚点精度 | 说明 |
| --- | --- | --- |
| `pymupdf` | 段落矩形 | 可定位到页内位置；本 skill 的默认层级 |
| `pdftotext` | 整页 | 只能判"这句话在这一页" |
| `ocr` | 整页 + 文本近似 | 措辞可能与原 PDF 有差异，`provenance.tier_note` 会注明 |

## 与字段的关系

- `sections[].evidence` 列出该节用到的锚点 id。
- `paper_card` 的 `_anchors` 列出卡片字段用到的锚点 id。
- `knowledge_points[].anchor` 指向单条锚点。
- `uncertainty.unanchored_claims` 列出没有锚点的精修内容。

一份健康的结果里，`verification.coverage` 应为 `1.0`；`partial` 状态下也要能指出
具体哪几条失败、为什么。
