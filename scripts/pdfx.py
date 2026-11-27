#!/usr/bin/env python3
"""pdfx -- layout-aware, page-anchored extraction for scientific papers.

The module turns a PDF into a *citable* representation:

    Document
      pages[]     ordered paragraphs, per-page text, column layout, bboxes
      sections[]  heading tree detected from the paper's own typography
      anchors     every paragraph carries a stable id + bbox + quote

Nothing here is paper-specific: section boundaries come from numbering,
relative type size and weight, not from a fixed template.  When several
extractors are available the same page text is produced by one tier and
cross-checked by another (see verify.py).

Tiers, best first:
  1. PyMuPDF (pymupdf / fitz)  - spans, fonts, bboxes, images
  2. pdftotext -layout          - poppler, text only (no bboxes)
  3. OCR (tesseract)            - last resort for scanned pages

Public API
----------
extract(path)              -> dict (document JSON, see schema.py)
page_text(doc, n)          -> str
find_paragraph(doc, pid)   -> paragraph dict | None
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import unicodedata

# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff]")
BOLD_FLAG = 16
SOFT_HYPHEN = "\u00ad"


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def has_cjk(text: str, ratio: float = 0.12) -> bool:
    if not text:
        return False
    return len(CJK_RE.findall(text)) / max(1, len(text)) > ratio


def collapse(text: str) -> str:
    """Whitespace-collapsed, hyphenation-safe comparison form (keeps case)."""
    t = nfkc(text).replace(SOFT_HYPHEN, "")
    t = re.sub(r"-\s*\n\s*", "-", t)
    t = t.replace("\n", " ")
    t = re.sub(r"[ \t\u00a0\u2000-\u200a]+", " ", t)
    return t.strip()


def squeeze(text: str) -> str:
    """Comparison key: collapsed, lowercased, no punctuation spacing."""
    return re.sub(r"\s+", "", collapse(text)).lower()


def join_lines(parts: list[str]) -> str:
    """Join PDF lines, undoing end-of-line hyphenation."""
    out = ""
    for raw in parts:
        piece = raw.strip()
        if not piece:
            continue
        if not out:
            out = piece
            continue
        prev = out[-1]
        if out.endswith("-") and not out.endswith("--"):
            if piece[0].islower():
                out = out[:-1] + piece
                continue
        if has_cjk(prev) and has_cjk(piece[0]):
            out += "" if re.search(r"[\u3000-\u303f\uff00-\uffef]$", out) is None else ""
            out += piece
        else:
            out += " " + piece
    return out


def header_key(text: str) -> str:
    """Key used to detect running headers/footers."""
    t = collapse(text).lower()
    return re.sub(r"\d+", "#", t)[:120]


# --------------------------------------------------------------------------
# tier 1: PyMuPDF
# --------------------------------------------------------------------------

def _fitz():
    try:  # PyMuPDF >= 1.24
        import pymupdf as fitz  # type: ignore
        return fitz
    except Exception:
        pass
    try:
        import fitz  # type: ignore
        return fitz
    except Exception:
        return None


def _raw_lines_pymupdf(fitz, page) -> list[dict]:
    """Character-level reconstruction: PDFs often encode spaces as glyph
    offsets, so span text arrives as `Weintroduceanew...`.  Reinsert a space
    where the horizontal gap between glyphs is wider than a normal advance."""
    data = page.get_text("rawdict")
    lines: list[dict] = []
    for block in data.get("blocks", []):
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            parts: list[str] = []
            sizes: list[float] = []
            bold_spans = 0
            prev_bbox = None
            for span in spans:
                size = float(span.get("size") or 0)
                sizes.append(size)
                font_name = (span.get("font") or "")
                flags = int(span.get("flags") or 0)
                if flags & BOLD_FLAG or any(k in font_name.lower() for k in ("bold", "black", "semibold")):
                    bold_spans += 1
                for ch in span.get("chars", []):
                    char = ch.get("c", "")
                    cbox = ch.get("bbox")
                    if not char:
                        continue
                    if char.strip() == "":
                        if parts and not parts[-1].endswith(" "):
                            parts.append(" ")
                        prev_bbox = cbox
                        continue
                    if prev_bbox is not None and cbox is not None and parts:
                        gap = cbox[0] - prev_bbox[2]
                        cjk_join = bool(CJK_RE.match(char)) and bool(CJK_RE.search(parts[-1][-1:]))
                        if gap > 0.26 * max(6.0, size) and not parts[-1].endswith(" ") and not cjk_join:
                            parts.append(" ")
                    parts.append(char)
                    prev_bbox = cbox
            text = re.sub(r"[ \t\u00a0]+", " ", "".join(parts)).strip()
            if not text:
                continue
            lines.append(
                {
                    "text": text,
                    "bbox": [float(v) for v in line.get("bbox", [0, 0, 0, 0])],
                    "size": round(max(sizes), 2),
                    "bold": bold_spans >= max(1, len(spans) // 2),
                    "font": (spans[0].get("font") or ""),
                }
            )
    return lines


# --------------------------------------------------------------------------
# reading order: full-width separators + column bands
# --------------------------------------------------------------------------

def _spans_gutter(line: dict, page_w: float) -> bool:
    x0, x1 = line["bbox"][0], line["bbox"][2]
    mid = page_w / 2.0
    return x0 < mid - 0.12 * page_w and x1 > mid + 0.12 * page_w


def _reading_order(lines: list[dict], page_w: float) -> list[dict]:
    if not lines:
        return []
    usable = [l for l in lines if l["bbox"][2] - l["bbox"][0] > 0.5] or lines
    if _layout_label(usable, page_w) != "two_column":
        return sorted(usable, key=lambda l: (round(l["bbox"][1], 1), l["bbox"][0]))
    # two columns: gutter-spanning elements split the page into vertical bands
    wide = [l for l in usable if (l["bbox"][2] - l["bbox"][0]) >= 0.78 * page_w or _spans_gutter(l, page_w)]
    wide_ids = {id(l) for l in wide}
    anchors = sorted(wide, key=lambda l: l["bbox"][1])
    bands: list[list[dict]] = []
    band: list[dict] = []
    ai = 0
    for line in sorted(usable, key=lambda l: (l["bbox"][1], l["bbox"][0])):
        while ai < len(anchors) and anchors[ai]["bbox"][1] + 1 < line["bbox"][1]:
            if band:
                bands.append(band)
                band = []
            bands.append([anchors[ai]])
            ai += 1
        if id(line) in wide_ids:
            continue
        band.append(line)
    if band:
        bands.append(band)
    while ai < len(anchors):
        bands.append([anchors[ai]])
        ai += 1

    mid = page_w / 2.0
    ordered: list[dict] = []
    for band in bands:
        if len(band) == 1:
            ordered.extend(band)
            continue
        left = [l for l in band if (l["bbox"][0] + l["bbox"][2]) / 2 < mid]
        right = [l for l in band if (l["bbox"][0] + l["bbox"][2]) / 2 >= mid]
        ordered.extend(sorted(left, key=lambda l: l["bbox"][1]))
        ordered.extend(sorted(right, key=lambda l: l["bbox"][1]))
    return ordered


def _layout_label(lines: list[dict], page_w: float) -> str:
    if not lines:
        return "empty"
    mid = page_w / 2.0
    left = sum(1 for l in lines if (l["bbox"][0] + l["bbox"][2]) / 2 < mid - 0.05 * page_w)
    right = sum(1 for l in lines if (l["bbox"][0] + l["bbox"][2]) / 2 > mid + 0.05 * page_w)
    narrow = sum(1 for l in lines if (l["bbox"][2] - l["bbox"][0]) < 0.6 * page_w)
    total = max(1, len(lines))
    if left / total > 0.22 and right / total > 0.22 and narrow / total > 0.55:
        return "two_column"
    return "single_column"


# --------------------------------------------------------------------------
# paragraph assembly
# --------------------------------------------------------------------------

_SENT_END = tuple(".!?。！？:;；：…\"'”’)）")


def _line_is_heading_like(line: dict, med_size: float, med_h: float) -> bool:
    text = line["text"].strip()
    if not text or len(text) > (52 if has_cjk(text) else 90):
        return False
    if text[-1:] in ".。;；,，":
        return False
    if NUM_HEAD.match(text) or BARE_NUM.match(text) or ROMAN_HEAD.match(text):
        return True
    if _match_known(text):
        return True
    return bool(line["bold"]) and med_size > 0 and line["size"] >= med_size * 0.99


def _assemble_paragraphs(lines: list[dict], page_no: int) -> list[dict]:
    if not lines:
        return []
    # discard rotated marginalia (arXiv stamps) and hairline slivers
    kept = []
    for line in lines:
        w = line["bbox"][2] - line["bbox"][0]
        h = line["bbox"][3] - line["bbox"][1]
        if h > 3 * max(w, 1.0) or (h > 0 and w / h < 0.08):
            continue
        kept.append(line)
    lines = kept
    if not lines:
        return []
    heights = [max(1.0, l["bbox"][3] - l["bbox"][1]) for l in lines]
    med_h = statistics.median(heights)
    med_size = statistics.median([l["size"] for l in lines if l["size"]]) if any(l["size"] for l in lines) else 0.0
    max_w = max((l["bbox"][2] - l["bbox"][0]) for l in lines) or 1.0
    paras: list[list[dict]] = []
    cur: list[dict] = []
    prev: dict | None = None
    for line in lines:
        if prev is None:
            cur = [line]
            prev = line
            continue
        gap = line["bbox"][1] - prev["bbox"][3]
        lh = max(1.0, prev["bbox"][3] - prev["bbox"][1])
        indent = line["bbox"][0] - prev["bbox"][0]
        big_size = line["size"] > prev["size"] * 1.15 or prev["size"] > line["size"] * 1.15
        short_prev = (prev["bbox"][2] - prev["bbox"][0]) < 0.88 * max_w
        new_para = (
            gap > 0.85 * max(lh, med_h)
            or gap < -lh
            or indent > max(4.0, 0.6 * lh)
            or big_size
            or _line_is_heading_like(prev, med_size, med_h)
            or (prev["text"][-1:] in _SENT_END and (short_prev or gap > 0.35 * max(lh, med_h)))
        )
        if new_para:
            paras.append(cur)
            cur = [line]
        else:
            cur.append(line)
        prev = line
    if cur:
        paras.append(cur)

    out: list[dict] = []
    for idx, group in enumerate(paras):
        text = join_lines([g["text"] for g in group])
        if not text.strip():
            continue
        x0 = min(g["bbox"][0] for g in group)
        y0 = min(g["bbox"][1] for g in group)
        x1 = max(g["bbox"][2] for g in group)
        y1 = max(g["bbox"][3] for g in group)
        out.append(
            {
                "id": f"p{page_no}_{idx + 1}",
                "page": page_no,
                "text": text,
                "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                "size": round(max(g["size"] for g in group), 2),
                "bold": any(g["bold"] for g in group),
                "n_lines": len(group),
            }
        )
    return out


# --------------------------------------------------------------------------
# running header / footer removal
# --------------------------------------------------------------------------

def _merge_continuations(pages: list[dict]) -> int:
    """Join a paragraph that starts mid-word/mid-sentence onto its predecessor.

    Column breaks and hyphenation leave fragments such as `Fine-tun` +
    `ing and auto-encoder ...`, which would otherwise become a bogus sentence
    and steal the section's conclusion slot.
    """
    joined = 0
    for page in pages:
        kept: list[dict] = []
        for para in page["paragraphs"]:
            text = para["text"].strip()
            prev = kept[-1] if kept else None
            if (
                prev is not None
                and text[:1].islower()
                and not has_cjk(text)
                and prev.get("role") != "footnote"
                and para.get("role") != "footnote"
                and not re.search(r"[.!?。！？:;]$", prev["text"].strip())
            ):
                tail = prev["text"].strip()
                last_word = re.split(r"\s+", tail)[-1] if tail else ""
                joiner = "" if (last_word and len(last_word) <= 7 and re.search(r"[a-z]$", last_word)) else " "
                prev["text"] = tail + joiner + text
                if prev.get("bbox") and para.get("bbox"):
                    prev["bbox"] = [
                        min(prev["bbox"][0], para["bbox"][0]), prev["bbox"][1],
                        max(prev["bbox"][2], para["bbox"][2]), max(prev["bbox"][3], para["bbox"][3]),
                    ]
                prev["n_lines"] = prev.get("n_lines", 1) + para.get("n_lines", 1)
                joined += 1
                continue
            kept.append(para)
        page["paragraphs"] = kept
    return joined


def _drop_running_furniture(pages: list[dict]) -> list[str]:
    counts: dict[str, int] = {}
    for page in pages:
        paras = page["paragraphs"]
        if not paras:
            continue
        for cand in (paras[0], paras[-1]):
            counts[header_key(cand["text"])] = counts.get(header_key(cand["text"]), 0) + 1
    n = max(1, len([p for p in pages if p["paragraphs"]]))
    repeated = {k for k, v in counts.items() if v >= max(3, int(0.28 * n)) and k}
    dropped: list[str] = []
    for page in pages:
        keep = []
        for idx, para in enumerate(page["paragraphs"]):
            edge = idx == 0 or idx == len(page["paragraphs"]) - 1
            if edge and header_key(para["text"]) in repeated:
                dropped.append(para["id"])
                continue
            keep.append(para)
        page["paragraphs"] = keep
    return dropped


# --------------------------------------------------------------------------
# section detection
# --------------------------------------------------------------------------

KNOWN_HEADINGS = {
    "abstract": ("abstract", 200),
    "摘要": ("abstract", 200),
    "introduction": ("introduction", 100),
    "引言": ("introduction", 100),
    "前言": ("introduction", 100),
    "related work": ("related_work", 90),
    "related works": ("related_work", 90),
    "background": ("background", 88),
    "相关工作": ("related_work", 90),
    "研究背景": ("background", 88),
    "method": ("method", 80),
    "methods": ("method", 80),
    "methodology": ("method", 80),
    "approach": ("method", 78),
    "proposed method": ("method", 78),
    "方法": ("method", 80),
    "实验": ("experiments", 70),
    "experiments": ("experiments", 70),
    "experimental setup": ("experiments", 66),
    "evaluation": ("evaluation", 64),
    "results": ("results", 60),
    "result": ("results", 60),
    "结果": ("results", 60),
    "discussion": ("discussion", 50),
    "讨论": ("discussion", 50),
    "conclusion": ("conclusion", 40),
    "conclusions": ("conclusion", 40),
    "结论": ("conclusion", 40),
    "limitations": ("limitations", 30),
    "局限": ("limitations", 30),
    "future work": ("future_work", 26),
    "acknowledg": ("acknowledgments", 20),
    "acknowledgments": ("acknowledgments", 20),
    "acknowledgements": ("acknowledgments", 20),
    "致谢": ("acknowledgments", 20),
    "references": ("references", 10),
    "bibliography": ("references", 10),
    "参考文献": ("references", 10),
    "appendix": ("appendix", 5),
    "附录": ("appendix", 5),
}

NUM_HEAD = re.compile(r"^\s*(?:第\s*)?(\d{1,2}(?:\.\d{1,2}){0,2})[\s\.、:：]+(\S.{0,90})$")
ROMAN_HEAD = re.compile(r"^\s*([IVX]{1,5})[\s\.、]+\s*(\S.{0,90})$")
BARE_NUM = re.compile(r"^\s*(?:\d{1,2}(?:\.\d{1,2}){0,2}|[A-Z]|[IVX]{1,5})\s*[\.、]?\s*$")
CN_NUM = re.compile(r"^\s*[一二三四五六七八九十]{1,3}[、\.]\s*(\S.{0,60})$")
ROMAN_VAL = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}


def _numeric_ratio(text: str) -> float:
    toks = [t for t in re.split(r"\s+", text) if t]
    if not toks:
        return 0.0
    numeric = sum(1 for t in toks if re.fullmatch(r"[\d\.,%‰±×xX\-–—/()\[\]]+", t))
    return numeric / len(toks)


def _merge_bare_number(paragraphs: list[dict], i: int) -> str | None:
    """`4` on its own line followed by `Ablation Studies` is one heading."""
    para = paragraphs[i]
    text = para["text"].strip()
    if not BARE_NUM.match(text) or i + 1 >= len(paragraphs):
        return None
    nxt = paragraphs[i + 1]
    if nxt["page"] != para["page"] or BARE_NUM.match(nxt["text"].strip()) or nxt["n_lines"] > 2:
        return None
    if para["bbox"] and nxt["bbox"]:
        gap = nxt["bbox"][1] - para["bbox"][3]
        if gap > 34:
            return None
    return f"{text} {nxt['text'].strip()}"


def _match_known(text: str):
    key = collapse(text.strip(" .。:：")).lower()
    if key in KNOWN_HEADINGS:
        return KNOWN_HEADINGS[key]
    for name, value in KNOWN_HEADINGS.items():
        if key.startswith(name) and len(key) - len(name) <= 3:
            return value
    return None


def _heading_candidates(paragraphs: list[dict], body_size: float, start_index: int) -> list[dict]:
    cands: list[dict] = []
    for i in range(start_index, len(paragraphs)):
        para = paragraphs[i]
        raw = para["text"].strip()
        if not raw or para["n_lines"] > 2:
            continue
        text = _merge_bare_number(paragraphs, i) or raw
        if len(text) > (58 if has_cjk(text) else 105):
            continue
        num = NUM_HEAD.match(text)
        roman = ROMAN_HEAD.match(text)
        known = _match_known(text)
        # a row of numbers is table data, not a heading -- unless the line
        # opens with a section number, which the sequence check will vet
        if _numeric_ratio(text) > 0.4 and not (num or roman or known):
            continue
        if re.search(r"\.{4,}", text):
            continue
        if text.rstrip()[-1:] in ".。,，;；" and not (num or known or roman):
            continue
        score = 0.0
        if known:
            score += 3.0
        if num:
            score += 2.0
        if roman:
            score += 1.8
        if CN_NUM.match(text):
            score += 1.4
        big = bool(body_size) and para["size"] >= body_size * 1.06
        if big:
            score += 1.2
        if para["bold"] and not has_cjk(text):
            score += 0.8
        if body_size and para["size"] and para["size"] < body_size * 0.95:
            score -= 1.6
        if re.match(r"^(fig|table|figure|图|表)\s*\d", text, re.I):
            score -= 3.0
        if score < 1.8:
            continue
        number = [int(x) for x in num.group(1).split(".")] if num else None
        if roman:
            number = [ROMAN_VAL.get(roman.group(1), 0)]
        cands.append(
            {
                "index": i,
                "pid": para["id"],
                "page": para["page"],
                "text": text,
                "title": (num.group(2).strip() if num else (roman.group(2).strip() if roman else text.strip(" .。:："))),
                "number": number,
                "known": known[0] if known else None,
                "known_rank": known[1] if known else 65,
                "big": big,
                "bold": bool(para["bold"]),
                "score": round(score, 2),
            }
        )
    return cands


def _select_headings(cands: list[dict]) -> list[dict]:
    """Enforce a coherent numbering sequence; that is what rejects table rows."""
    accepted: list[dict] = []
    last_top = 0
    for cand in cands:
        number = cand["number"]
        level = 1
        if number:
            if len(number) == 1:
                n = number[0]
                if n not in (last_top + 1, last_top, last_top + 2, 1) or (n == 1 and last_top > 1):
                    continue
                last_top = max(last_top, n) if n != 1 or last_top == 0 else last_top
                level = 1
            else:
                # a chapter number can be missing from the text layer while its
                # subsections survive; let a first subsection open the chapter
                if number[0] == last_top:
                    level = min(3, len(number))
                elif number[0] == last_top + 1 and number[-1] == 1:
                    last_top = number[0]
                    level = min(3, len(number))
                else:
                    continue
                if number[-1] > 40:
                    continue
        elif cand["known"]:
            level = 2 if cand["known"] in ("limitations", "future_work") else 1
            if cand["known"] in ("abstract", "references"):
                level = 1
        else:
            if not accepted or not (cand["bold"] or cand["big"]):
                continue
            level = 2
        title_text = (cand.get("title") or "").strip()
        if len(title_text) < (2 if has_cjk(title_text) else 3):
            continue
        if accepted:
            prev = accepted[-1]
            if (collapse(prev["title"]).lower() == collapse(cand["title"]).lower()
                    and prev["page"] == cand["page"]):
                continue  # the number and its title were separate paragraphs
        cand = dict(cand, level=level)
        accepted.append(cand)
    # a level-2 heading cannot open the document
    while accepted and accepted[0]["level"] > 1:
        accepted.pop(0)
    for i, cand in enumerate(accepted):
        cand["id"] = f"S{i + 1:02d}"
    return accepted


def _build_sections(paragraphs: list[dict], headings: list[dict]) -> list[dict]:
    if not headings:
        return []
    idx_of = {p["id"]: i for i, p in enumerate(paragraphs)}
    sections: list[dict] = []
    for i, head in enumerate(headings):
        start = idx_of.get(head["pid"], 0)
        end = idx_of.get(headings[i + 1]["pid"], len(paragraphs)) if i + 1 < len(headings) else len(paragraphs)
        end = max(end, start + 1)
        body = paragraphs[start + 1 : end]
        sections.append(
            {
                "id": head["id"],
                "title": head["title"],
                "full_heading": head["text"],
                "kind": head["known"],
                "level": head["level"],
                "rank": head["known_rank"],
                "anchor_pid": head["pid"],
                "page_start": head["page"],
                "page_end": body[-1]["page"] if body else head["page"],
                "paragraph_ids": [p["id"] for p in body],
                "n_paragraphs": len(body),
                "n_chars": sum(len(p["text"]) for p in body),
            }
        )
    merged: list[dict] = []
    for sec in sections:
        if merged and sec["n_paragraphs"] == 0 and merged[-1]["n_paragraphs"] == 0:
            merged[-1]["page_end"] = sec["page_end"]
            continue
        merged.append(sec)
    ref_i = next((i for i, s in enumerate(merged) if s["kind"] == "references"), None)
    for i, sec in enumerate(merged):
        sec["is_back_matter"] = bool(ref_i is not None and i >= ref_i)
    return merged


# --------------------------------------------------------------------------
# quantitative evidence
# --------------------------------------------------------------------------

NUM_TOKEN = re.compile(r"\d+(?:\.\d+)?\s*(?:%|‰|pp|x|×|B|M|K|k|亿|万|倍|percent)?")


def _numbers(text: str) -> list[str]:
    return [m.group(0).strip() for m in NUM_TOKEN.finditer(text) if len(m.group(0).strip()) > 0]


def _sentence_split(text: str) -> list[str]:
    if has_cjk(text):
        parts = re.split(r"(?<=[。！？；])", text)
    else:
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(\[])", text)
    return [p.strip() for p in parts if p.strip()]


def _quantitative_sentences(paragraphs: list[dict], limit: int = 12) -> list[dict]:
    found = []
    for para in paragraphs:
        for sent in _sentence_split(para["text"]):
            nums = _numbers(sent)
            if len(nums) >= 2 and 20 <= len(sent) <= 400:
                found.append({"pid": para["id"], "page": para["page"], "text": sent, "numbers": nums[:8]})
        if len(found) >= limit:
            break
    return found[:limit]


# --------------------------------------------------------------------------
# captions (figures / tables)
# --------------------------------------------------------------------------

CAP_RE = re.compile(r"^\s*(fig(?:ure)?\.?\s*(\d{1,2})|表\s*(\d{1,2})|table\s*(\d{1,2})|图\s*(\d{1,2}))\s*[\.:：]?\s*(.{0,240})", re.I)


def _captions(paragraphs: list[dict]) -> list[dict]:
    caps = []
    for para in paragraphs:
        m = CAP_RE.match(para["text"])
        if not m:
            continue
        head = m.group(1)
        num = next((g for g in (m.group(2), m.group(3), m.group(4), m.group(5)) if g), None)
        if num is None:
            continue
        kind = "figure" if re.match(r"(fig|图)", head, re.I) else "table"
        caps.append(
            {
                "kind": kind,
                "label": f"{kind} {num}",
                "page": para["page"],
                "text": collapse(para["text"])[:400],
                "pid": para["id"],
                "bbox": para["bbox"],
            }
        )
    return caps


# --------------------------------------------------------------------------
# tier 2: pdftotext
# --------------------------------------------------------------------------

def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _pdftotext(path: str) -> list[str] | None:
    exe = _which("pdftotext")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-layout", "-enc", "UTF-8", path, "-"],
            capture_output=True,
            timeout=180,
            check=False,
        )
    except Exception:
        return None
    if out.returncode != 0 or not out.stdout:
        return None
    pages = out.stdout.decode("utf-8", "replace").split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return pages


# --------------------------------------------------------------------------
# OCR tier (scanned pages)
# --------------------------------------------------------------------------

def _ocr_available() -> str | None:
    return _which("tesseract")


def _ocr_pages(path: str, fitz) -> list[str] | None:
    exe = _ocr_available()
    if not exe or fitz is None:
        return None
    import tempfile

    texts: list[str] = []
    tmp = tempfile.mkdtemp(prefix="pdfx_ocr_")
    try:
        doc = fitz.open(path)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=300)
            img = os.path.join(tmp, f"p{i}.png")
            pix.save(img)
            lang = "chi_sim+eng"
            res = subprocess.run(
                [exe, img, "stdout", "-l", lang, "--psm", "3"],
                capture_output=True,
                timeout=300,
                check=False,
            )
            if res.returncode != 0:
                res = subprocess.run([exe, img, "stdout", "-l", "eng", "--psm", "3"],
                                     capture_output=True, timeout=300, check=False)
            texts.append(res.stdout.decode("utf-8", "replace") if res.stdout else "")
        return texts
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# document assembly
# --------------------------------------------------------------------------

def _doc_meta(fitz, path: str, doc) -> dict:
    meta = {"file": os.path.basename(path), "bytes": os.path.getsize(path)}
    try:
        meta["sha256"] = hashlib.sha256(open(path, "rb").read()).hexdigest()
    except Exception:
        meta["sha256"] = None
    try:
        info = doc.metadata or {}
        for key in ("title", "author", "subject", "creator", "producer", "creationDate", "modDate"):
            if info.get(key):
                meta[key] = info[key]
        meta["encrypted"] = bool(getattr(doc, "is_encrypted", False))
        meta["needs_pass"] = bool(getattr(doc, "needs_pass", False))
    except Exception:
        pass
    return meta


def _front_matter(paragraphs: list[dict], body_size: float) -> tuple[int, dict]:
    """Locate where the body starts and salvage title/author lines."""
    start = 0
    for i, para in enumerate(paragraphs[:60]):
        kind = _match_known(para["text"])
        if kind and kind[0] == "abstract":
            start = i
            break
    else:
        for i, para in enumerate(paragraphs[:80]):
            m = NUM_HEAD.match(para["text"].strip())
            if m and m.group(1) == "1":
                start = i
                break
    title = None
    authors: list[str] = []
    head = [p for p in paragraphs[: max(start, 1)] if p["page"] == paragraphs[0]["page"]] if paragraphs else []
    head = [p for p in head if _match_known(p["text"]) is None]
    if head:
        best = max(head, key=lambda p: (p["size"], len(p["text"])))
        if best["size"] >= max(body_size * 1.25, body_size + 2.0) and len(best["text"]) > 8:
            title = best["text"]
            ti = head.index(best)
            tail_words = ("for", "of", "and", "the", "in", "with", "to", "a", "an", "on", "by", "via", "from")
            while ti + 1 < len(head):
                nxt = head[ti + 1]
                if abs(nxt["size"] - best["size"]) > max(1.5, body_size * 0.12) or len(title) > 220:
                    break
                words = title.strip().split()
                last = words[-1].lower() if words else ""
                if last in tail_words or nxt["text"][:1].islower():
                    title = f"{title} {nxt['text']}".strip()
                    ti += 1
                    continue
                break
            for para in head[ti + 1 :]:
                t = para["text"]
                if not (2 < len(t) < 160):
                    continue
                if re.search(r"@|universit|institut|abstract|correspond|http|google", t, re.I):
                    continue
                if collapse(t) and collapse(t) in collapse(title):
                    continue
                if t.rstrip()[-1:] in ".":
                    continue
                authors.append(t)
    return start, {"title": title, "authors": authors[:8]}


def extract(path: str, max_pages: int | None = None) -> dict:
    """Extract a layout-aware document representation.

    Returns a JSON-safe dict; see `schema.py` for the contract of each part.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    fitz = _fitz()
    warnings: list[str] = []
    tier = "none"

    pages: list[dict] = []
    doc = None

    if fitz is not None:
        try:
            doc = fitz.open(path)
            if getattr(doc, "needs_pass", False):
                raise PermissionError("password-protected PDF")
            n = len(doc)
            limit = min(n, max_pages) if max_pages else n
            tier = "pymupdf"
            for pno in range(limit):
                page = doc[pno]
                raw = _raw_lines_pymupdf(fitz, page)
                ordered = _reading_order(raw, page.rect.width)
                paras = _assemble_paragraphs(ordered, pno + 1)
                body = "\n\n".join(p["text"] for p in paras)
                pages.append(
                    {
                        "page": pno + 1,
                        "width": round(page.rect.width, 1),
                        "height": round(page.rect.height, 1),
                        "layout": _layout_label(raw, page.rect.width),
                        "n_lines": len(raw),
                        "n_images": len([b for b in page.get_text("dict").get("blocks", []) if b.get("type") == 1]),
                        "paragraphs": paras,
                        "text": body,
                    }
                )
        except Exception as exc:  # fall through to weaker tiers
            warnings.append(f"pymupdf failed: {type(exc).__name__}: {exc}")
            pages = []
            tier = "none"
            doc = None

    if not pages:
        alt = _pdftotext(path)
        if alt:
            tier = "pdftotext"
            for i, page_text in enumerate(alt, start=1):
                paras = []
                for j, chunk in enumerate([c.strip() for c in re.split(r"\n\s*\n", page_text) if c.strip()]):
                    paras.append(
                        {
                            "id": f"p{i}_{j + 1}",
                            "page": i,
                            "text": collapse(chunk),
                            "bbox": None,
                            "size": 0.0,
                            "bold": False,
                            "n_lines": chunk.count("\n") + 1,
                        }
                    )
                pages.append(
                    {
                        "page": i,
                        "width": 0.0,
                        "height": 0.0,
                        "layout": "unknown",
                        "n_lines": page_text.count("\n") + 1,
                        "n_images": 0,
                        "paragraphs": paras,
                        "text": "\n\n".join(p["text"] for p in paras),
                    }
                )

    if not pages or sum(len(p["paragraphs"]) for p in pages) <= 2:
        ocr = _ocr_pages(path, fitz)
        if ocr:
            tier = "ocr"
            warnings.append("no usable text layer; OCR text is approximate and anchors are page-level only")
            pages = []
            for i, page_text in enumerate(ocr, start=1):
                paras = []
                for j, chunk in enumerate([c.strip() for c in re.split(r"\n\s*\n", page_text) if c.strip()]):
                    paras.append(
                        {
                            "id": f"p{i}_{j + 1}",
                            "page": i,
                            "text": collapse(chunk),
                            "bbox": None,
                            "size": 0.0,
                            "bold": False,
                            "n_lines": chunk.count("\n") + 1,
                        }
                    )
                pages.append(
                    {
                        "page": i,
                        "width": 0.0,
                        "height": 0.0,
                        "layout": "scanned",
                        "n_lines": page_text.count("\n") + 1,
                        "n_images": 0,
                        "paragraphs": paras,
                        "text": "\n\n".join(p["text"] for p in paras),
                    }
                )

    if not pages:
        warnings.append("no text could be extracted (scanned or image-only PDF without OCR)")
        return {
            "ok": False,
            "tier": "none",
            "file": os.path.basename(path),
            "pages": [],
            "sections": [],
            "captions": [],
            "meta": {"file": os.path.basename(path)},
            "warnings": warnings,
            "status": "unreadable",
        }

    dropped = _drop_running_furniture(pages)
    joined_fragments = _merge_continuations(pages)

    all_paras = [p for page in pages for p in page["paragraphs"]]
    if not all_paras:
        return {
            "ok": False,
            "tier": tier,
            "file": os.path.basename(path),
            "pages": pages,
            "sections": [],
            "captions": [],
            "meta": {"file": os.path.basename(path)},
            "warnings": warnings + ["pages contain no text paragraphs"],
            "status": "unreadable",
        }

    # body text size = size that covers the most characters
    size_weight: dict[float, int] = {}
    for p in all_paras:
        if p["size"]:
            size_weight[p["size"]] = size_weight.get(p["size"], 0) + len(p["text"])
    body_size = max(size_weight, key=size_weight.get) if size_weight else 0.0

    # footnotes: smaller type in the bottom band of the page
    if body_size:
        for page in pages:
            page_h = page.get("height") or 0
            for para in page["paragraphs"]:
                bbox = para.get("bbox")
                if not bbox or not page_h:
                    continue
                if para["size"] and para["size"] < body_size * 0.93 and bbox[1] > page_h * 0.84:
                    para["role"] = "footnote"

    front_end, front = _front_matter(all_paras, body_size)
    cands = _heading_candidates(all_paras, body_size, front_end)
    headings = _select_headings(cands)
    sections = _build_sections(all_paras, headings)

    captions = _captions(all_paras)
    meta = _doc_meta(fitz, path, doc) if doc is not None else {"file": os.path.basename(path)}
    if fitz is not None and doc is not None:
        try:
            meta["pages"] = len(doc)
        except Exception:
            meta["pages"] = len(pages)

    if not sections:
        warnings.append("no section headings detected; notes fall back to page-level grouping")

    return {
        "ok": True,
        "tier": tier,
        "file": os.path.basename(path),
        "meta": meta,
        "front_matter": front,
        "body_size": body_size,
        "pages": pages,
        "sections": sections,
        "captions": captions,
        "dropped_furniture": dropped,
        "merged_fragments": joined_fragments,
        "warnings": warnings,
        "status": "ok" if sections else "partial",
    }


def page_text(doc: dict, page_no: int) -> str:
    for page in doc.get("pages", []):
        if page["page"] == page_no:
            return page["text"]
    return ""


def find_paragraph(doc: dict, pid: str) -> dict | None:
    for page in doc.get("pages", []):
        for para in page["paragraphs"]:
            if para["id"] == pid:
                return para
    return None


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: pdfx.py <paper.pdf> [--out extract.json] [--max-pages N]", file=sys.stderr)
        return 2
    path = argv[1]
    out = None
    max_pages = None
    i = 2
    while i < len(argv):
        if argv[i] == "--out" and i + 1 < len(argv):
            out = argv[i + 1]
            i += 2
        elif argv[i] == "--max-pages" and i + 1 < len(argv):
            max_pages = int(argv[i + 1])
            i += 2
        else:
            i += 1
    doc = extract(path, max_pages=max_pages)
    payload = json.dumps(doc, ensure_ascii=False)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(payload)
        n_sec = len(doc.get("sections", []))
        n_par = sum(len(p["paragraphs"]) for p in doc.get("pages", []))
        print(json.dumps({"ok": doc.get("ok"), "tier": doc.get("tier"), "sections": n_sec,
                          "paragraphs": n_par, "pages": len(doc.get("pages", [])),
                          "warnings": doc.get("warnings", [])}, ensure_ascii=False))
    else:
        print(payload)
    return 0 if doc.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
