# 评审与自查清单 / Evaluation checklist

## 一、10 分钟评审法

1. **看骨架**：`sections[].title` 与 PDF 目录/章节标题逐条对照。缺章、错层、凭空多出的小节，
   都是"没对得上"。
2. **看证据**：随机抽 3 条 `anchors`，用 `quote` 在 PDF 里搜索该页，是否命中。
   再用 `page` 验证页码是否真是那一页（PDF 阅读器页码可能偏移 1，属已知问题，需在
   `provenance` 说明）。
3. **看诚实度**：`limitations_kind`、`uncertainty` 是否覆盖"论文没说"的项。
   `unanchored_claims` 为空是加分项，不为空但明确标注也是合格项；**未标注的推测是扣分项**。
4. **看可用性**：`knowledge_points.csv` 能否直接导入表格；`paper_card` 字段能否与另一篇论文并排比较。
5. **看复跑**：同一条命令重跑一次，章节数与锚点数是否稳定。

## 二、机器可判定项（脚本 + selftest）

| 检查 | 方式 |
| --- | --- |
| 顶层字段齐全 | `selftest.py` |
| 锚点 id 唯一、引文非空、有核验结论 | `selftest.py` |
| `page_start <= page_end`、层级为正整数 | `selftest.py` |
| 章节引用锚点存在 | `selftest.py` |
| `coverage` 与 `verified/total` 自洽 | `selftest.py` |
| `status=success` 时不存在失败锚点 | `selftest.py` |
| 契约字段已登记 | `selftest.py` |

## 三、必须人工确认项

| 检查 | 为什么机器判不了 |
| --- | --- |
| 章节标题是否等于论文原名 | 标题可能被编号/断行改写 |
| 摘要与结论是否"读懂了" | 抽取句正确 ≠ 概括正确 |
| `limitations_kind=inferred` 的推断是否站得住 | 需要领域判断 |
| 术语合并是否合理 | `MLM` 与 `Masked LM` 合并安全，`BERT` 与 `BERT-base` 不安全 |
| 数字是否被误解（% vs 百分点） | 抽取保留原文，但换算可能出错 |

## 四、本 skill 的本地验证记录

| 案例 | 形态 | 页数 | 章节 | 锚点 | 覆盖率 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| BERT (arXiv 1810.04805) | 英文双栏 ACL | 16 | 19 | 109 | 1.00 | success |
| 中文样例 | 中文单栏 | 1 | 5 | 11 | 1.00 | success |
| 扫描件（BERT 前 3 页栅格化） | 无文本层 | 3 | 0 | 0 | 0.00 | unanswerable（`handoff`=OCR） |

对照点：BERT 的 19 个章节与论文实际结构一致（Abstract、1、2、2.1–2.3、3、3.1、3.2、4、4.1–4.4、5、5.1–5.3、6）。

## 五、复跑命令

```bash
python3 scripts/notes.py run --case-dir /input --out /app/work/baseline
python3 scripts/notes.py run --case-dir /input --out /app/output --judgments judgments.json
python3 scripts/notes.py verify --out /app/output
python3 scripts/selftest.py --out /app/output
```

期望：最后两步退出码为 0；`selftest` 输出 `{"ok": true}`。
