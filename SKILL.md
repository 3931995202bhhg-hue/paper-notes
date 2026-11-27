---
name: paper-notes
description: "把真实论文 PDF 变成与原文章节一一对应、字段齐备、可回链核对的结构化笔记。读取 case.json/task.md，按论文自身的章节（含二级小节）切分，为每条结论保留页码与段落锚点并重新核验，输出 result.json、notes.md、paper_card.json、anchors.jsonl、knowledge_points.csv。触发于：文献总结、论文笔记、结构化笔记、章节总结、论文卡片、知识点提取、精读论文、读这篇论文、做读书笔记、summarize this paper、take notes on this PDF、structured literature notes、paper card、extract knowledge points。"
---

# 论文结构化笔记 / Paper Notes

一份可复核的论文笔记必须同时满足四件事：**骨架对得上**（章节与论证顺序来自论文本身）、
**内容留得住**（研究问题、数据、方法条件、主要发现、局限）、**证据找得回**（页码/段落/图表，
不是笼统出处）、**结果用得上**（可检索、可比较、可继续加工）。本 skill 的每一步都围绕这四件事，
并且在读数、抽字段、写结论之间保留一条可验证的链条。

## 何时使用

- 用户给出一篇论文（PDF）或一个案例目录，要求总结、精读、做笔记、提取知识点、做论文卡片。
- 任务要求"按章节""保留页码""能回到原文"的笔记。
- 需要在多篇论文之间用同一套字段比较（综述、开题、文献矩阵）。

## 何时不用

- 只要求一句话摘要、翻译全文、或复现论文数值/图表 → 用对应专用 skill。
- 输入不是论文（专利、幻灯片、网页）时仍可用，但要在 `uncertainty` 里注明材料类型，
  不要套用"研究问题/方法/实验"的措辞去描述非研究文本。

## 输入

| 输入 | 必需 | 说明 |
| --- | --- | --- |
| `/input/case.json` | 建议 | `case_id`、论文路径、`output_contract`（字段清单） |
| `/input/task.md` | 建议 | 任务类型与交付要求；缺失时按"结构化笔记"处理并记录 |
| 论文 PDF | 必需 | 文本层完好、扫描件、双栏、中英文混合都支持；读到什么算什么 |

`case.json` 里的论文键可能是 `paper` / `papers` / `input` / `files`，值是路径、列表或对象；
脚本会自动定位，找不到就把目录里所有 PDF 列为候选，并在 `uncertainty` 里说明来源。

## 输出（契约优先）

先满足 `output_contract`，再补齐本 skill 的规范字段。**契约字段永远出现在 `result.json` 顶层**，
缺失的字段写 `null` 并登记到 `output_contract.missing`，绝不用编造内容填充。

| 文件 | 内容 |
| --- | --- |
| `result.json` | 主交付：契约字段 + 规范字段（见下） |
| `notes.md` | 人读版：一页摘要、论文卡片、逐章笔记（含页码引用） |
| `paper_card.json` | 跨论文可比较的统一卡片 |
| `anchors.jsonl` | 每条锚点一行：页、段落 id、引文、矩形、核验结果 |
| `knowledge_points.csv` | 知识点表，便于检索与导入 |
| `manifest.json` / `run.log` | 产物哈希、抽取层级、耗时、告警 |

`result.json` 的规范字段：

```json
{
  "case_id": "…", "status": "success|partial|unanswerable",
  "sections": [{"id","title","level","page_start","page_end","status",
                "objective","key_points","methods","results","conclusion","limitations",
                "continuity":{"opens_with","previous_tail","link"},
                "evidence":[anchor_id],"anchors":[anchor_id]}],
  "paper_card": {"title","authors","year","venue","doi","paper_type",
                 "research_question","data","methods","findings","conclusions",
                 "limitations","limitations_kind","summary","references"},
  "knowledge_points": [{"id","term","canonical","kind","statement","aliases","section","page","confidence","anchor"}],
  "anchors": [{"id","pid","page","section","sentence","kind","quote","truncated","bbox","verified","verify_method"}],
  "verification": {"anchors_total","anchors_verified","anchors_failed","coverage","method"},
  "uncertainty": [{"kind","detail"}],
  "provenance": {"extractor","body_size","warnings","generated_at","skill_version","elapsed_s"},
  "output_contract": {"declared","satisfied","missing"},
  "change_log": [{"when","what","why"}]
}
```

字段含义、取值与机器可判定边界见 `references/output-contract.md` 与 `references/field-dictionary.md`。

## 五步流程

### Step 0 — 先确认输入边界（不要急着读全文）

```bash
python3 scripts/notes.py run --case-dir /input --out /app/output
```

这一步同时完成 Step 1 与 Step 2，并立刻产出一份**可交付的抽取式基线**。先跑它，
再决定要改哪里：失败时就地留下 `result.json`（`status=unanswerable` 且写明原因），
不要把失败拖到最后。

阅读 `run.log` 确认三件事：论文是否找到、抽取层级（`pymupdf`/`pdftotext`/`ocr`）、
检测到的章节数与锚点覆盖率。章节数为 0 或覆盖率为 0 时，按"失败与降级"处理。

### Step 1 — 版式感知抽取（脚本负责，不要手工抄正文）

`scripts/pdfx.py` 做四件事，缺一不可：

1. **字符级重建**：PDF 常用字形位移代替空格，直接取 span 会得到
   `Weintroduceanewlanguage...`；这里按字形间距回填空格。
2. **阅读顺序**：识别双栏，用横跨版心的元素（标题、宽表）切分纵向带，带内先左栏后右栏，
   避免"左右栏交错"和"标题排在正文之后"。
3. **段落重建**：按行距、缩进、字号突变、标题行切段；跨页与跨栏的断词片段（`Fine-tun`+`ing`）
   合并回原段落；页眉页脚、脚注、旋转水印单独标记，不进入笔记。
4. **章节识别**：用编号、字号、字重、中英文常用章节名共同判定，并要求**编号连续**——
   这一条把"82.3 / 94.9"这类表格数字行排除在标题之外；编号在文本层丢失时，
   允许由二级小节（`3.1`）开启新章。

抽取结果落 `extract.json`（可单独运行）：

```bash
python3 scripts/notes.py extract --pdf paper.pdf --out extract.json
```

### Step 2 — 生成锚点基线

对每个章节，脚本从句子里挑目的、方法、结果、结论、局限，全部**逐字取自原文**，
并各带一个锚点。挑选规则是可解释的：线索词 + 数字密度 + 位置先验，
被选中的句子不会在字段之间重复使用。

锚点格式：

```json
{"id":"A0007","pid":"p4_12","page":4,"section":"S09","sentence":0,
 "quote":"…逐字引文，≤220 字符…","truncated":false,
 "bbox":[72.0,483.6,290.3,494.5],"verified":true,"verify_method":"bbox_clip"}
```

### Step 3 — 语义精修（唯一需要模型判断的一步）

脚本给的是抽取式基线：句子是对的，但组织方式还不像"人写的笔记"。此时写一份
`judgments.json`，只改需要改的字段：

```json
{
  "paper_card": {
    "research_question": {"text": "…", "evidence": ["p1_9"]},
    "limitations": {"text": "…", "evidence": ["p9_4"], "kind": "inferred"}
  },
  "sections": {
    "S09": {
      "objective": {"text": "…", "evidence": ["p4_12"]},
      "key_points": [{"text": "…", "evidence": ["p4_12", "p5_3"]}]
    }
  },
  "knowledge_points": [{"term": "MLM", "statement": "…", "evidence": ["p3_7"]}],
  "uncertainty": ["论文未报告消融实验的随机种子"]
}
```

规则：

- **每条精修都带 `evidence`**（段落 id）。没有证据的句子仍会保留，但会进入
  `uncertainty.unanchored_claims`，并在覆盖率里体现——我们不假装它是原文。
- 区分 `kind: "stated"`（论文明说）与 `kind: "inferred"`（你的推断）。评审最先看这一栏。
- 论文没报告的东西写成 `null` + `uncertainty`，不要补一个"看起来合理"的数字。

```bash
python3 scripts/notes.py run --case-dir /input --out /app/output --judgments judgments.json
```

### Step 4 — 锚点核验（不通过就降级）

核验不信任抽取管线自己的段落文本，而是重新打开 PDF，在锚点矩形内重新抽取文本比对；
矩形不可用（`pdftotext`/OCR 层级）时退回整页文本包含比对，最后再用原生文本搜索兜底。

```bash
python3 scripts/notes.py verify --out /app/output
```

- 全部通过 → `status=success`，`verification.coverage=1.0`。
- 有失败 → 自动 `status=partial`，失败锚点写入 `uncertainty.anchor_failures`，
  **不要手工把 `verified` 改成 `true`**。
- 失败通常意味着该段落被跨栏切断：回到 `extract.json` 看 `pid` 的 `bbox` 是否跨越版心。

### Step 5 — 交付与状态

`status` 只有三种，按事实选：

| status | 含义 | 必须携带 |
| --- | --- | --- |
| `success` | 章节齐全、锚点核验通过 | 覆盖率、章节数 |
| `partial` | 有字段缺失、锚点失败或材料不完整 | 缺什么、为什么、可否补 |
| `unanswerable` | 无法读取或缺少关键材料 | 原因 + 人工接管位置 |

最后在回复里给一段不超过 200 字的交付说明：读了哪篇、几章、锚点覆盖率、哪些字段
依赖人工确认。**不要把 `notes.md` 全文复制到对话里**——它在文件里。

## 失败与降级

| 情况 | 检测方式 | 处理 |
| --- | --- | --- |
| 扫描件/无文本层 | 抽取段落数 ≤2 或 `pages` 为空 | 若有 `tesseract` 走 OCR 层级并在 `provenance.tier_note` 标注"文本近似"；否则 `unanswerable` + 需 OCR 的页码 |
| 加密/权限受限 | `needs_pass` 为真 | `unanswerable`，提示提供密码或已解密副本 |
| 双栏错序 | 版式判定为 `two_column` 但段落首尾不连贯 | 已在阅读顺序层处理；仍异常时把该页列入 `uncertainty` |
| 图表/公式缺失 | 文本层无对应对象 | 在 `objects`/`uncertainty` 里记"该图未进入文本层"，不臆测图意 |
| 超长文献（>100 页） | 页数阈值 | `--max-pages` 截断并注明"仅读到第 N 页"，状态改 `partial` |
| 非中文/中英混排 | 字符统计 | 语言写入 `provenance`；中文按句号切句，英文按 `.?!` 且避开缩写 |
| 章节识别为 0 | `sections=[]` | 退回按页分组，`status=partial`，并列出页码区间供人工切章 |
| 契约字段未知 | `output_contract.missing` 非空 | 该字段置 `null`，在 `uncertainty` 说明"契约要求的字段无法从原文落地" |

## 质量自检（交付前逐条过）

1. **骨架一致**：`sections[].title` 是否等于论文原章节名？层级是否与编号深度一致？
2. **页段正确**：`page_start/page_end` 是否与 `notes.md` 里引用的页码自洽？
3. **证据可回链**：随机抽 3 条锚点，用 `quote` 在 PDF 里搜索，是否命中同一页？
4. **字段完备**：研究问题、数据、方法、发现、局限是否都有值或明确 `null` + 原因？
5. **未报告不编造**：`uncertainty` 是否覆盖了"论文没说"的项？
6. **可复跑**：删掉 `out/` 重跑同一条命令，`result.json` 的章节与锚点数是否一致？

自检脚本（对已生成的产物做结构校验）：

```bash
python3 scripts/selftest.py --out /app/output
```

## 预算与性能

- 抽取是纯本地计算：16 页双栏论文约 1–3 秒，100 页约 20–40 秒，不消耗模型请求。
- 精修只需要 1–3 次模型请求（每次只看证据包，不看全文），远低于 64 次预算。
- 900 秒预算下，建议把时间留给核验和精修，不要用模型逐页读 PDF。

## 目录

```
SKILL.md                 本文件
scripts/notes.py         入口：run / extract / verify
scripts/pdfx.py          版式感知抽取与章节识别
scripts/compose.py       字段抽取、judgments 合并、markdown 渲染
scripts/anchors.py       锚点模型与独立核验
scripts/contract.py      case.json / output_contract 解析与契约填充
scripts/selftest.py      产物结构自检
references/              输出契约、字段字典、锚点规范、判定边界、失败手册
templates/               notes 模板、paper card 模板、judgments 模板
examples/                最小可运行示例（示意输出，非正式答案）
```
