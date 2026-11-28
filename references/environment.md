# 运行环境 / Environment

本 skill 只需要 Python 3.9+。下面三层依赖按需安装，缺一层就自动降级（见 `robustness.md`），
不会因为缺少某个包而直接失败。

## 依赖矩阵

| 组件 | 作用 | 缺失时 |
| --- | --- | --- |
| Python 3.9+ | 运行 `scripts/*.py`（标准库优先） | 无法运行 |
| `pymupdf>=1.23` | 字形坐标、段落矩形 → **段落级锚点** | 降级为 `pdftotext`（整页锚点） |
| `pypdf>=4.0`（可选） | 页数/加密状态的第二意见 | 忽略 |
| `pdftotext`（poppler-utils） | 二级文本抽取 | 降级为 OCR |
| `tesseract-ocr` + `chi_sim`/`eng` | 扫描件 OCR | 扫描件返回 `unanswerable` |

安装：

```bash
pip install -r requirements.txt
# Debian/Ubuntu 上的系统依赖
apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim
```

## 容器配方（文本形式，便于直接复制）

```dockerfile
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app
ENTRYPOINT ["python3", "/app/scripts/notes.py"]
CMD ["run", "--case-dir", "/input", "--out", "/app/output"]
```

## 入口

```bash
# 一个案例的完整流程
python3 scripts/notes.py run --case-dir /input --out /app/output
python3 scripts/notes.py verify --out /app/output
python3 scripts/selftest.py --out /app/output
```

## 资源约束（与赛题约定一致）

- 全部资源为 UTF-8 文本文件：≤50 个、单个 ≤500 KB、合计 ≤2 MB、无符号链接。
- 运行期产物（`result.json`、`anchors.jsonl` 等）由脚本生成，不随 skill 分发。
- 不依赖作者个人路径、不依赖网络、不依赖手工步骤。
