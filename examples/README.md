# 示例 / Examples

本目录是**示意输出**，用于说明接口与排版，不是正式案例答案，也不代表任何论文的完整结论。

| 文件 | 说明 |
| --- | --- |
| `example-result.json` | 真实运行结果裁剪后的结构样例（保留前 3 节与对应锚点） |
| `example-notes.md` | 同一份结果的 `notes.md` 视图 |
| `example-judgments.json` | 精修契约的写法示例（带 evidence 与 `kind`） |

来源：BERT（arXiv 1810.04805）在 `pymupdf` 层级上的实际运行结果，裁剪到 3 节、
13 条锚点，并重算了 `verification`。未被保留的章节不是"省略"，只是示例体积控制。

最小调用：

```bash
python3 scripts/notes.py run --case-dir /input --out /app/output
python3 scripts/notes.py run --case-dir /input --out /app/output --judgments examples/example-judgments.json
```

注意：`example-judgments.json` 里的段落 id（`p1_9` 等）只对同一篇论文的同一次抽取有效。
换论文时必须用该次 `extract.json` 里的 id，否则证据会被忽略并在 `run.log` 里告警。
