# 字段字典 / Field dictionary

每个字段标注**由谁判定**：`机器` 指脚本可独立核验，`模型` 指需要阅读判断，`人工` 指必须人工确认。
评审可以用这一列区分"看起来对"和"确实可核"。

## `paper_card`

| 字段 | 类型 | 判定 | 取值与来源 |
| --- | --- | --- | --- |
| `title` | string | 机器 | 第一页最大字号段落，跨行标题自动续接；PDF 元数据仅作兜底 |
| `authors` | string[] | 机器 | 标题之后、摘要之前的短行；过滤邮箱/机构/URL |
| `year` / `venue` / `doi` | string | 模型 | 文本层常缺；模板字段保留，`null` 表示未报告 |
| `paper_type` | string | 机器 | 由标题与章节名判定：`empirical` / `review` / `dataset` / `theory` |
| `research_question` | string | 模型 | 摘要中"提出/关注/目标"句；须带 evidence |
| `data` | string[] | 模型 | 数据集、语料、样本量与划分；逐字取自原文 |
| `methods` | string[] | 混合 | 方法章节要点句（抽取）+ 精修 |
| `findings` | string[] | 混合 | 含数字与比较的结果句 |
| `conclusions` | string[] | 模型 | 结论章节的判断 |
| `limitations` | string[] | 模型 | 论文自述局限；`kind: stated` |
| `limitations_kind` | string | 机器 | `stated`（原文明确）/ `none_found`（未找到）/ `inferred`（模型推断，必须带 evidence 与理由） |
| `summary` | string | 机器 | 摘要前 3 句逐字拼接 |
| `references` | int | 机器 | 参考文献条目的近似计数（`[n]` / `(2020)` 模式） |

**边界**：`paper_type=empirical` 不代表论文一定是实证研究，只是一个路由标签；
若论文同时是综述与实证，写 `review` 并在 `uncertainty` 注明。

## `sections[]`

| 字段 | 类型 | 判定 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 机器 | `S01`…，按论文顺序连续 |
| `title` | string | 机器 | 去掉编号后的章节名，与原文同名 |
| `full_heading` | string | 机器 | 含编号的原始标题行（如 `3.1 Pre-training BERT`） |
| `level` | int | 机器 | 编号深度：`1`、`1.1` → 2、`1.1.1` → 3；无编号标题按字号/字重定级 |
| `kind` | string | 机器 | `abstract` / `introduction` / `related_work` / `method` / `experiments` / `results` / `discussion` / `conclusion` / `limitations` / `references` / `appendix` |
| `page_start` / `page_end` | int | 机器 | 标题页与末段页 |
| `n_paragraphs` / `n_words` | int | 机器 | 规模，用于识别"标题下面没内容" |
| `status` | string | 机器 | `ok`（≥2 个要点）/ `thin`（1 个）/ `empty`（0 个） |
| `objective` | string | 混合 | 本节要解决的问题；优先"本节/本文/我们提出"句 |
| `key_points` | string[] | 混合 | 3–4 条，不与 objective/conclusion 重复 |
| `methods` | string[] | 混合 | 方法条件（模型、数据、超参、流程） |
| `results` | string[] | 混合 | 定量结果（数字 + 指标名 + 比较对象） |
| `conclusion` | string | 混合 | 本节收束句 |
| `limitations` | string[] | 模型 | 本节自述的局限 |
| `continuity` | object | 机器+模型 | `opens_with`（本节首句）、`previous_tail`（上节末句）、`link`：`explicit_reference` / `implicit` / `start` |
| `evidence` / `anchors` | string[] | 机器 | 本节引用的锚点 id |
| `extractive` | bool | 机器 | `true` 表示全为原文句子，未被模型改写 |

`continuity` 是"章节之间的承接关系"的机读投影：它不改写原文，只用两句逐字引文
说明"上一节停在哪、这一节从哪起"，因此可以直接核对。

## `knowledge_points[]`

| 字段 | 说明 |
| --- | --- |
| `term` / `canonical` | 原写法与归一键（小写、去空白），用于跨论文合并 |
| `kind` | `abbreviation` / `concept` / `method` / `metric` / `section_concept` |
| `statement` | 一句话说明；缩写给出展开式 |
| `aliases` | 同义词/缩写/全称，用于检索 |
| `section` / `page` / `anchor` | 出处 |
| `confidence` | 0–1；`0.8` 表示原文明确给出定义，`0.5` 表示由上下文匹配 |

术语冲突（同词不同义、同义不同词）不合并、不覆盖，两条都保留并在 `uncertainty` 标记
`kind: "term_conflict"`。

## `uncertainty[]`

| `kind` | 触发 |
| --- | --- |
| `stated_gap` | 论文未报告（无随机种子、无能耗等） |
| `anchor_failures` | 锚点核验未通过 |
| `unanchored_claims` | 精修内容没有 evidence |
| `term_conflict` | 术语冲突 |
| `input` | 多篇只读第一篇、缺少 case.json/task.md |
| `extraction` | 抽取层级降级或告警 |
| `blocked` | `unanswerable` 的具体原因 |
| `declared` | 模型/human 主动声明的其他不确定 |

## `provenance`

| 字段 | 说明 |
| --- | --- |
| `extractor` | `pymupdf` / `pdftotext` / `ocr` / `none` |
| `body_size` | 正文主字号，用于解释标题判定 |
| `warnings` | 抽取层告警原文 |
| `tier_note` | 该层级能提供什么精度的锚点 |
| `generated_at` / `elapsed_s` / `skill_version` | 复跑与对比所需 |
