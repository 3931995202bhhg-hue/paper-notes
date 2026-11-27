# paper-notes

把真实论文 PDF 变成**章节对齐、字段齐备、可回链核对**的结构化笔记。

读者拿到一份 PDF，最想要的不是「压缩后的通读摘要」，而是：骨架和论文一致、关键前提不丢、
每条结论都能翻回原页。这个仓库把这件事做成了一个可执行的 skill：

- **骨架来自论文自身**：用编号连续性、字号、字重识别章节（含二级小节），表格数字行会被编号校验排除。
- **字段可并排比较**：统一 `paper_card`（研究问题 / 数据 / 方法 / 发现 / 局限）。
- **每条结论都能回链**：锚点带页码、段落 id、逐字引文、页内矩形；核验时重开 PDF 在矩形内比对，
  不信任抽取管线自己的文本。
- **没报告的就说没报告**：`status`、`limitations_kind`、`uncertainty` 三处共同表达「论文没说」。

## 快速开始

```bash
pip install -r requirements.txt     # 可选：只有 pymupdf 能解锁段落级锚点

# 1) 直接产出可交付的抽取式基线（不需要模型参与）
python3 scripts/notes.py run --case-dir /input --out /app/output

# 2) 需要更像"人写的笔记"时，写一份 judgments.json 再跑
python3 scripts/notes.py run --case-dir /input --out /app/output --judgments judgments.json

# 3) 核验 + 结构自检
python3 scripts/notes.py verify --out /app/output
python3 scripts/selftest.py --out /app/output
```

`/input` 目录里放 `case.json`（`case_id`、论文路径、`output_contract`）、`task.md` 和论文 PDF。
只需要 Python 3.9+；没有 `pymupdf` 时自动退回 `pdftotext`，再退回 OCR。

## 输出

| 文件 | 用途 |
| --- | --- |
| `result.json` | 机器读取的主交付（契约字段 + 规范字段） |
| `notes.md` | 人读版笔记（一页摘要、论文卡片、章节地图、逐章笔记、锚点索引） |
| `paper_card.json` | 跨论文比较用卡片 |
| `anchors.jsonl` | 逐条锚点（页、段落、引文、核验结果） |
| `knowledge_points.csv` | 知识点表，可直接导入表格 |
| `manifest.json` / `run.log` | 产物哈希、抽取层级、耗时、告警 |

## 实测

| 案例 | 形态 | 章节 | 锚点 | 覆盖率 | 状态 |
| --- | --- | --- | --- | --- | --- |
| BERT（arXiv 1810.04805） | 英文双栏 16 页 | 19 | 109 | 1.00 | success |
| 中文样例 | 中文单栏 | 5 | 11 | 1.00 | success |
| 扫描件（无文本层） | 扫描 PDF | 0 | 0 | — | unanswerable（给 OCR 接管点） |

BERT 的 19 节与论文真实结构逐条吻合：Abstract、1、2.1–2.3、3.1–3.2、4.1–4.4、5.1–5.3、6。
`examples/` 里是同一篇论文裁剪后的示意输出（不是正式答案）。

## 目录

```
SKILL.md              技能正文（模型读这一份）
scripts/              抽取、组装、锚点核验、契约解析、自检
references/           输出契约、字段字典、锚点规范、精修契约、失败手册、评审清单
templates/            笔记模板、卡片模板、judgments 模板
examples/             最小示例（示意输出）
Dockerfile            可选：带 poppler + tesseract 的运行环境
```

## 诚实边界

- 扫描件在 OCR 层级只有整页锚点，措辞可能有偏差，`provenance.tier_note` 会注明。
- 公式与图片不进入文本层时，只记录「未覆盖」，不推断内容。
- `status=partial` 是有意义的交付，不是失败：它会指出缺什么、能否补。

## 许可

MIT，见 [LICENSE](LICENSE)。
