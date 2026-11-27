# 精修契约 / judgments.json

`judgments.json` 是唯一允许模型改写的入口。它不重写整份笔记，只覆盖需要判断的字段，
并按段落 id 挂证据。这样"模型写了什么"和"原文说了什么"始终可分离。

## 结构

```json
{
  "paper_card": {
    "research_question": {"text": "…", "evidence": ["p1_9"]},
    "data": {"text": "…", "evidence": ["p3_2"]},
    "limitations": {"text": "…", "evidence": ["p9_4"], "kind": "inferred"},
    "paper_type": "empirical"
  },
  "sections": {
    "S09": {
      "objective": {"text": "…", "evidence": ["p4_12"]},
      "key_points": [{"text": "…", "evidence": ["p4_12", "p5_3"]}],
      "results": [{"text": "…", "evidence": ["p8_2"]}],
      "limitations": [{"text": "…", "evidence": ["p9_4"]}]
    }
  },
  "knowledge_points": [
    {"term": "MLM", "statement": "…", "evidence": ["p4_6"], "kind": "method", "aliases": ["Masked LM"]}
  ],
  "uncertainty": [
    "论文未报告预训练总能耗的测量方式",
    {"kind": "stated_gap", "detail": "未给出随机种子"}
  ]
}
```

## 取值规则

| 键 | 可写 | 说明 |
| --- | --- | --- |
| `paper_card.*` | 任意卡片字段 | `research_question`/`data`/`methods`/`findings`/`conclusions`/`limitations` 建议用对象形式带 evidence |
| `paper_card.limitations.kind` | `stated` / `inferred` | `inferred` 必须能指向 evidence，并在正文里说明推断依据 |
| `sections.Sxx.objective` | string 或 `{text,evidence}` | 覆盖抽取结果 |
| `sections.Sxx.key_points/methods/results/limitations` | 数组，元素同上 | **整体替换**，不是追加 |
| `knowledge_points[]` | 对象数组 | 追加/补全；同 `canonical` 不重复合并 |
| `uncertainty[]` | string 或 `{kind,detail}` | 追加到最终 `uncertainty` |

## 硬规则

1. **没有 evidence 就进 `unanchored_claims`**：内容仍然保留，但会被标为无证据，
   并体现在评审可读的 `uncertainty` 里。不要为了"看起来完整"删掉证据要求。
2. **不改原文措辞**：`quote` 必须逐字；精修 `text` 是笔记语言（可以改写），
   但**不得引入原文没有的数字、结论或因果关系**。
3. **`null` 优于猜测**：论文没报告的量写 `null` 并登记 `stated_gap`。
4. **不改 `status`**：`success/partial/unanswerable` 由脚本按事实判定。
5. **不改 `pid`**：段落 id 只能来自 `extract.json`；引用不存在的 id 会被忽略并记入告警。

## 常见正例与反例

| 反例 | 问题 | 正例 |
| --- | --- | --- |
| `"findings": "BERT 大幅超越所有模型"` | 无数字、无比较对象、无证据 | `{"text": "GLUE 80.5%，相对提升 7.7 个点", "evidence": ["p1_11"]}` |
| `"limitations": {"text": "算力需求大", "kind": "stated"}` | 原文没写，标成 stated 即造假 | `kind: "inferred"` + evidence 指向方法章节 |
| `"objective": "…", "evidence": ["p99_1"]` | 不存在的段落 id | 用 `extract.json` 里实际存在的 id |
| 把 `key_points` 填成 objective 的重复 | 信息冗余 | 写方法条件或结论差异 |

## 何时不该用 judgments

- 抽取式基线已经准确且可读时——精修只会引入风险。先看 `notes.md`，只改真正需要的字段。
- 材料不可读（`unanswerable`）时——先解决 OCR/解密，再谈精修。
