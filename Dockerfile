FROM python:3.11-slim

# poppler-utils gives `pdftotext` (tier 2); tesseract gives the OCR fallback.
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

# The evaluator mounts the skill at /skills/weekly-skill and the case at /input.
# Default invocation reproduces the documented pipeline end to end.
ENTRYPOINT ["python3", "/app/scripts/notes.py"]
CMD ["run", "--case-dir", "/input", "--out", "/app/output"]
