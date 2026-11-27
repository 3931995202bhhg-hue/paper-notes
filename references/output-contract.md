# 输出契约 / Output contract

## 优先级

1. `case.json` 的 `output_contract`（或 `outputContract` / `contract` / `expected_outputs` / `result_schema`）
   声明的字段，**必须出现在 `result.json` 顶层**，字段名按声明原样保留。
2. 契约里出现、但本 skill 的规范结构没有对应项时，按 `scripts/contract.py` 的别名表解析
   （例如 `summary` → `paper_card.summary`，`evidence` → `anchors`）。
3. 无法落地的契约字段写 `null`，并登记进 `output_contract.missing`，**不编造**。
4. 契约没有声明的字段，仍然按下方规范结构全部输出——契约是最低要求，不是上限。

`task.md` 里若以「输出字段 / output contract / 交付字段」列出字段名，脚本会解析为契约来源
`task.md`；两者都没有时，来源记为 `inferred`，并在 `uncertainty` 说明。

## `output_contract` 自身

```json
{"source": "case.json:output_contract|task.md|inferred",
 "declared": ["case_id", "sections", "..."],
 "satisfied": ["..."],
 "missing": ["..."]}
```

判定规则：字段存在且不是 `null` / 空字符串即 `satisfied`；列表与对象允许为空
（"本文没有可报告的局限"是有效结论，不等于字段缺失）。

## `result.json` 规范结构

| 键 | 类型 | 必出 | 说明 |
| --- | --- | --- | --- |
| `case_id` | string | 是 | 输入标识；`case.json` 未声明时用目录名，并记入 `uncertainty` |
| `status` | string | 是 | `success` / `partial` / `unanswerable` |
| `task_kinds` | string[] | 是 | 从 `task.md` 识别：notes / summarize / qa / translate / extract / verify / knowledge |
| `language` | string | 是 | `zh` / `en` / `unknown` |
| `paper` | object | 是 | `file`、`sha256`、`pages`、`front_matter` |
| `paper_card` | object | 是 | 跨论文可比较的卡片，见字段字典 |
| `sections` | object[] | 是 | 章节笔记，顺序 = 论文顺序 |
| `knowledge_points` | object[] | 是 | 术语/方法/指标条目 |
| `key_points` | string[] | 是 | 全文要点（章节要点的去重汇总） |
| `anchors` | object[] | 是 | 全部锚点，见 `anchor-spec.md` |
| `verification` | object | 是 | `anchors_total`、`anchors_verified`、`anchors_failed`、`coverage`、`method`、`failures` |
| `uncertainty` | object[] | 是 | 未报告、无法判断、材料冲突、锚点失败、无证据精修 |
| `provenance` | object | 是 | 抽取层级、正文字号、告警、时间、skill 版本、耗时 |
| `change_log` | object[] | 是 | 每次改动：时间、动作、原因 |
| `handoff` | object | 否 | `status=unanswerable` 时给出人工接管位置 |
| `notes_markdown` | string | 是 | 与 `notes.md` 内容一致 |

## `status` 判定

| 取值 | 条件 |
| --- | --- |
| `success` | 抽取层级可用、检测到章节、锚点全部通过、契约字段无缺失 |
| `partial` | 上述任一不满足但仍有可交付内容（章节为 0、锚点失败、字段缺失、超长截断、多篇只读第一篇） |
| `unanswerable` | 无文本层/加密/无 PDF，且无法降级；必须给 `reason` 与 `handoff` |

脚本自动判定，不需要模型拍板；模型只能在 `uncertainty` 里补充理由，**不能把 `partial` 写成 `success`**。

## 契约与文件的关系

`result.json` 是唯一被机器读取的交付物；`notes.md`、`paper_card.json`、`anchors.jsonl`、
`knowledge_points.csv` 是同一份内容的不同视图，不允许与 `result.json` 冲突。
任何一处修改都应重跑 `notes.py run`，由脚本统一重写全部视图。
