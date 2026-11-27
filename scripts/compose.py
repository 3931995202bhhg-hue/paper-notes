#!/usr/bin/env python3
"""compose -- turn an extracted document into section-aligned, anchored notes.

Design rules that keep the output honest:

* Every generated sentence is taken **verbatim** from the paper and carries an
  anchor; nothing is paraphrased by the script.
* A field the paper does not discuss is `null` plus an uncertainty entry --
  never an invented statement.
* A model (or human) may refine fields through `judgments.json`; refinements
  keep their evidence pids, and anything supplied without evidence is listed
  as unanchored instead of being quietly trusted.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time

import anchors as anchor_mod
from pdfx import collapse, find_paragraph, has_cjk, _sentence_split

CUE = {
    "objective": (
        "we propose", "we present", "we introduce", "we describe", "this paper", "in this work",
        "our goal", "we aim", "this section", "we study", "we investigate", "本节", "本文", "我们提出",
        "我们的目标", "旨在",
    ),
    "method": (
        "we train", "we use", "we apply", "we adopt", "objective", "architecture", "algorithm",
        "we optimize", "we fine-tune", "we pretrain", "loss function", "采用", "使用", "训练", "方法",
        "模型结构", "目标函数",
    ),
    "results": (
        "we achieve", "outperform", "improves", "results show", "we observe", "achieves", "reduces",
        "compared to", "table", "figure", "提升", "优于", "结果", "达到", "下降",
    ),
    "conclusion": (
        "we conclude", "in summary", "overall", "we have shown", "in this paper we", "to conclude",
        "综上", "因此", "结论", "总而言之",
    ),
    "limitation": (
        "limitation", "future work", "however", "cannot", "remains", "open question", "局限", "不足",
        "未来工作", "尚需",
    ),
}
METRICS = re.compile(
    r"\b(BLEU|ROUGE|F1|accuracy|precision|recall|AUC|RMSE|MAE|MSE|perplexity|GLUE|SQuAD|"
    r"exact match|EM|IoU|SSIM|PSNR|R2|R²)\b|准确率|召回率|精确率|误差",
    re.I,
)
NUMBER = re.compile(r"\d+(?:\.\d+)?\s*(?:%|‰|pp|B|M|K|k|万|亿|倍|points?|分)?")


class AnchorFactory:
    def __init__(self):
        self.items: list[dict] = []
        self._seen: set[tuple] = {}

    def by_id(self, anchor_id: str):
        for anchor in self.items:
            if anchor["id"] == anchor_id:
                return anchor
        return None

    def add(self, doc, paragraph, sentence_index, section_id, quote=None, truncated=False,
            kind="text", origin="extractive"):
        key = (paragraph["id"], sentence_index)
        if key in self._seen:
            return self._seen[key]
        if quote is None:
            quote, sentence_index2, truncated2 = anchor_mod.make_quote(paragraph, sentence_index)
            truncated = truncated or truncated2
        anchor = anchor_mod.make_anchor(
            f"A{len(self.items) + 1:04d}", doc, paragraph, section_id, quote,
            sentence_index=sentence_index, kind=kind, truncated=truncated, origin=origin,
        )
        self.items.append(anchor)
        self._seen[key] = anchor
        return anchor


def _numeric_ratio_local(text: str) -> float:
    toks = [t for t in re.split(r"\s+", text or "") if t]
    if not toks:
        return 0.0
    numeric = sum(1 for t in toks if re.fullmatch(r"[\d\.,%‰±×xX\-–—/()\[\]]+", t))
    return numeric / len(toks)


LEADING_STOPWORDS = {
    "and", "or", "the", "a", "an", "of", "in", "for", "to", "with", "as", "such",
    "by", "from", "using", "trained", "called", "known", "this", "these", "its",
}


def _clean_expansion(expansion: str, limit: int = 5) -> str:
    words = [w for w in re.split(r"\s+", expansion.strip()) if w]
    while words and words[0].lower().strip(".,;:") in LEADING_STOPWORDS:
        words.pop(0)
    if len(words) > limit:
        words = words[:limit]
    text = " ".join(words).strip(" ,;:")
    return text


def _section_sentences(doc: dict, section: dict) -> list[dict]:
    out = []
    title_key = collapse(section.get("title") or "").lower()
    for pid in section["paragraph_ids"]:
        para = find_paragraph(doc, pid)
        if not para or para.get("role") == "footnote":
            continue
        for si, sent in enumerate(_sentence_split(para["text"])):
            text = sent.strip()
            if len(text) < 12 or not re.search(r"[A-Za-z\u4e00-\u9fff]", text):
                continue
            if si == 0 and title_key and collapse(text).lower() == title_key:
                continue
            if re.match(r"^[\(（]?\d{4}[a-z]?[\)）]", text):
                continue  # dangling citation fragment from a column break
            out.append({"pid": pid, "page": para["page"], "si": si, "text": text, "para": para})
    return out


def _is_own_limitation(text: str) -> bool:
    """Only limitations the paper attributes to itself."""
    low = text.lower()
    if re.search(r"局限|不足", text):
        return True  # Chinese papers often state these without a pronoun
    if not re.search(r"limitation|future work|尚未|未解决", low):
        return False
    return bool(re.search(r"\bour\b|\bthis work\b|\bthis paper\b|\bwe\b", low))


def _score(sent: dict, field: str, position: int, total: int) -> float:
    text = sent["text"].lower()
    score = 0.0
    for cue in CUE[field]:
        if cue in text:
            score += 1.3
    if field == "results":
        score += min(3, 0.7 * len(NUMBER.findall(sent["text"])))
        if METRICS.search(sent["text"]):
            score += 0.8
    if field == "limitation":
        score += 0.6 if 8 <= len(sent["text"]) <= 320 else -0.4
    # positional priors
    if field == "objective" and position <= 1:
        score += 1.4
    if field == "conclusion" and position >= total - 2:
        score += 1.4
    if field == "method" and position <= 2:
        score += 0.4
    length = len(sent["text"])
    if length < 35:
        score -= 0.8
    if length > 480:
        score -= 0.8
    return score


def _pick(sents: list[dict], field: str, used: set[str], limit: int = 2, floor: float = 0.9) -> list[dict]:
    scored = []
    total = max(1, len(sents))
    for idx, sent in enumerate(sents):
        if sent["pid"] + f"#{sent['si']}" in used:
            continue
        scored.append((_score(sent, field, idx, total), sent))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    out = []
    for score, sent in scored:
        if score < floor or len(out) >= limit:
            break
        key = sent["pid"] + f"#{sent['si']}"
        used.add(key)
        out.append(sent)
    return out


def _draft_section(doc, section, factory, used):
    sents = _section_sentences(doc, section)
    if not sents:
        return {
            "id": section["id"], "title": section["title"], "level": section["level"],
            "page_start": section["page_start"], "page_end": section["page_end"],
            "n_paragraphs": section.get("n_paragraphs", 0),
            "status": "empty", "objective": None, "key_points": [], "methods": [],
            "results": [], "conclusion": None, "limitations": [],
            "continuity": {"opens_with": None, "previous_tail": None, "link": "implicit"},
            "evidence": [], "anchors": [], "n_words": 0, "extractive": True,
        }
    objective = _pick(sents, "objective", used, limit=1, floor=0.6)
    methods = _pick(sents, "method", used, limit=2, floor=0.8)
    results = _pick(sents, "results", used, limit=2, floor=0.8)
    conclusion = _pick(sents, "conclusion", used, limit=1, floor=1.0)
    if not conclusion:
        for closing in reversed(sents):
            key = closing["pid"] + f"#{closing['si']}"
            if key in used or len(closing["text"]) < 40:
                continue
            if closing["text"].rstrip()[-1:] not in ".!?。！？":
                continue
            used.add(key)
            conclusion = [closing]
            break
    lim_pool = sents if section.get("kind") == "limitations" else [
        s for s in sents if _is_own_limitation(s["text"])
    ]
    limitation = _pick(lim_pool, "limitation", used, limit=1, floor=0.4) if lim_pool else []
    key_pool = objective + methods + results + conclusion
    if not key_pool:
        key_pool = _pick(sents, "objective", used, limit=3, floor=-99)
    evidence = [factory.add(doc, item["para"], item["si"], section["id"])["id"] for item in key_pool]

    text_len = sum(len(s["text"]) for s in sents)
    status = "ok" if len(key_pool) >= 2 else ("thin" if key_pool else "empty")
    note = {
        "id": section["id"],
        "title": section["title"],
        "full_heading": section.get("full_heading"),
        "level": section["level"],
        "kind": section.get("kind"),
        "page_start": section["page_start"],
        "page_end": section["page_end"],
        "n_paragraphs": section["n_paragraphs"],
        "n_words": len(re.findall(r"\w+|[\u4e00-\u9fff]", " ".join(s["text"] for s in sents))) if sents else 0,
        "status": status,
        "objective": objective[0]["text"] if objective else None,
        "key_points": [s["text"] for s in (objective + results + methods)[:4]],
        "methods": [s["text"] for s in methods],
        "results": [s["text"] for s in results],
        "conclusion": conclusion[0]["text"] if conclusion else None,
        "limitations": [s["text"] for s in limitation],
        "evidence": evidence,
        "anchors": list(evidence),
        "extractive": True,
    }
    # continuity: verbatim opening of this section + verbatim tail of the previous
    note["continuity"] = {
        "opens_with": sents[0]["text"] if sents else None,
        "previous_tail": None,
        "link": "implicit",
    }
    return note


def _continuity(notes: list[dict]) -> None:
    cues = ("previous section", "as described above", "as shown in", "building on", "section",
            "上一节", "如前所述", "上文", "接下来")
    for i, note in enumerate(notes):
        cont = note.get("continuity") or {}
        if i == 0:
            note["continuity"] = {"opens_with": cont.get("opens_with"),
                                  "previous_tail": None, "link": "start"}
            continue
        prev = notes[i - 1]
        open_text = (cont.get("opens_with") or "").lower()
        link = "explicit_reference" if any(c in open_text for c in cues[:5]) else "implicit"
        note["continuity"] = {
            "opens_with": cont.get("opens_with"),
            "previous_tail": prev.get("conclusion") or (prev["key_points"][-1] if prev.get("key_points") else None),
            "link": link,
        }


def _abs_sentences(doc, sections):
    for section in sections:
        if section.get("kind") == "abstract":
            return _section_sentences(doc, section), section
    # no abstract heading: use the first 3 paragraphs of the body
    picked = []
    for page in doc.get("pages", [])[:1]:
        for para in page["paragraphs"][:6]:
            for si, sent in enumerate(_sentence_split(para["text"])):
                picked.append({"pid": para["id"], "page": para["page"], "si": si,
                               "text": sent, "para": para})
    return picked, None


def _paper_card(doc, sections, notes, factory):
    abs_sents, abs_sec = _abs_sentences(doc, sections)
    used: set[str] = set()
    section_of = {}
    for section in sections:
        for pid in section["paragraph_ids"]:
            section_of.setdefault(pid, section["id"])

    def first(cues, limit=2, pool=None):
        pool = pool if pool is not None else abs_sents
        hits = [s for s in pool if any(c in s["text"].lower() for c in cues)]
        return hits[:limit]

    def anchor_for(item, kind="text"):
        sec_id = section_of.get(item["pid"], abs_sec["id"] if abs_sec else "front")
        return factory.add(doc, item["para"], item["si"], sec_id, kind=kind)

    question = first(("we propose", "we present", "this paper", "we introduce", "本文", "我们提出"), 1)
    if not question and abs_sents:
        question = abs_sents[:1]

    data = first(("dataset", "corpus", "training data", "we evaluate on", "benchmark", "数据", "语料", "数据集"), 3)
    findings = first(("we achieve", "outperform", "results show", "improv", "state-of-the-art", "结果", "优于", "提升"), 3)
    limitations = []
    for note in notes:
        for text in note.get("limitations") or []:
            limitations.append(text)

    card = {
        "title": doc.get("front_matter", {}).get("title") or doc.get("meta", {}).get("title"),
        "authors": doc.get("front_matter", {}).get("authors") or [],
        "year": None,
        "venue": None,
        "doi": None,
        "language": None,
        "pages": len(doc.get("pages", [])),
        "paper_type": _paper_type(doc, sections),
        "research_question": question[0]["text"] if question else None,
        "data": [s["text"] for s in data],
        "methods": list(dict.fromkeys(m for n in notes[:3] for m in n["methods"]))[:3],
        "findings": [s["text"] for s in findings],
        "conclusions": None,
        "limitations": limitations[:4],
        "limitations_kind": "stated" if limitations else "none_found",
        "summary": None,
        "references": _reference_count(doc),
        "fields": {},
    }
    card["summary"] = " ".join(s["text"] for s in abs_sents[:3]) if abs_sents else None
    card["_anchors"] = [anchor_for(s)["id"] for s in (question + data + findings) if s]
    if not limitations:
        card["limitations_note"] = "paper states no explicit limitation in the sections read"
    return card


def _paper_type(doc, sections) -> str:
    titles = " ".join((s["title"] or "").lower() for s in sections)
    if "survey" in titles or "review" in titles or "综述" in titles:
        return "review"
    if "benchmark" in titles or "dataset" in titles:
        return "dataset"
    if "theorem" in titles or "proof" in titles:
        return "theory"
    return "empirical"


def _reference_count(doc) -> int | None:
    for section in doc.get("sections", []):
        if section.get("kind") == "references":
            text = " ".join(
                p["text"] for pid in section["paragraph_ids"]
                if (p := find_paragraph(doc, pid))
            )
            approx = len(re.findall(r"\[\d{1,3}\]|（\d{1,3}）|\(\d{4}[a-z]?\)", text))
            return approx or None
    return None


def _knowledge_points(doc, sections, notes, factory):
    points = []
    seen = {}
    section_of = {}
    for section in sections:
        for pid in section["paragraph_ids"]:
            section_of.setdefault(pid, section["id"])

    def add(term, statement, pid, si, kind, aliases=None, confidence=0.6):
        canon = re.sub(r"\s+", " ", term).strip().lower()
        if not canon or len(canon) < 2:
            return
        if canon in seen:
            entry = seen[canon]
            for alias in aliases or []:
                if alias and alias not in entry["aliases"]:
                    entry["aliases"].append(alias)
            return
        para = find_paragraph(doc, pid)
        if not para:
            return
        anchor = factory.add(doc, para, si, section_of.get(pid, "front"))
        entry = {
            "id": f"K{len(points) + 1:03d}",
            "term": term.strip(),
            "canonical": canon,
            "kind": kind,
            "statement": statement,
            "aliases": list(dict.fromkeys([a for a in (aliases or []) if a])),
            "section": section_of.get(pid, "front"),
            "page": para["page"],
            "confidence": confidence,
            "anchor": anchor["id"],
        }
        points.append(entry)
        seen[canon] = entry

    # abbreviation definitions: "X (ABBR)" and "ABBR, which stands for"
    ABBR = re.compile(r"(?:^|(?<=[\s(,;:]))([A-Za-z][A-Za-z0-9\- ]{2,48}?)\s*\(([A-Z]{2,8})\)")
    for page in doc.get("pages", []):
        for para in page["paragraphs"]:
            if para.get("role") == "footnote":
                continue
            text = para["text"]
            if _numeric_ratio_local(text) > 0.35 or para.get("n_lines", 1) > 14:
                continue  # table rows and reference lists, not definitions
            for match in ABBR.finditer(text):
                expansion = _clean_expansion(match.group(1))
                if len(expansion) < 4 or _numeric_ratio_local(expansion) > 0.3:
                    continue
                if expansion.split()[0].lower() == "and":
                    continue
                add(match.group(2), f"{match.group(2)} = {expansion}", para["id"], 0,
                    "abbreviation", aliases=[expansion], confidence=0.8)
            for match in re.finditer(r"(?:^|(?<=[\s,;:]))([A-Z]{2,8})\s*(?:stands for|refers to|即|是指)\s*([^.;。；]{3,80})", text):
                add(match.group(1), f"{match.group(1)} — {match.group(2).strip()}", para["id"], 0,
                    "abbreviation", confidence=0.75)
            for match in re.finditer(r"(?:^|(?<=[\s,;:]))([^.;。；]{2,40}?)\s*(?:is defined as|refers to|is called|称为|定义为)\s*([^.;。；]{3,80})", text):
                if _numeric_ratio_local(match.group(1)) > 0.3:
                    continue
                add(match.group(1), f"{match.group(1).strip()} — {match.group(2).strip()}", para["id"], 0,
                    "concept", confidence=0.6)

    # method/variable/metric knowledge from section headings and key points
    for note in notes:
        for sentence in (note["results"] or [])[:1]:
            if not note["evidence"]:
                continue
            first_anchor = factory.by_id(note["evidence"][0])
            if not first_anchor:
                continue
            pid = first_anchor["pid"]
            for metric in sorted(set(m.group(0) for m in METRICS.finditer(sentence))):
                add(metric, sentence, pid, 0, "metric", confidence=0.5)

    for section in sections:
        if section["level"] <= 2 and section.get("kind") not in ("references", "appendix"):
            title = (section["title"] or "").strip()
            if 3 <= len(title) <= 80:
                para = find_paragraph(doc, section["anchor_pid"])
                if para:
                    add(title, section.get("full_heading") or title, para["id"], 0, "section_concept",
                        confidence=0.55)
    return points


def build(doc: dict, case: dict, judgments: dict | None = None, pdf_path: str | None = None) -> dict:
    factory = AnchorFactory()
    used: set[str] = set()
    sections = [s for s in doc.get("sections", []) if not s.get("is_back_matter") and s.get("n_paragraphs")]
    notes = [_draft_section(doc, s, factory, used) for s in sections]
    _continuity(notes)
    card = _paper_card(doc, sections, notes, factory)
    card["methods"] = [m for n in notes[:3] for m in n["methods"]][:3] or card["methods"]
    points = _knowledge_points(doc, sections, notes, factory)

    # ---- apply model/human judgments -------------------------------------
    unanchored: list[str] = []
    if judgments:
        _apply_judgments(judgments, notes, card, points, factory, doc, unanchored)

    result = {
        "case_id": case["case_id"],
        "status": "success",
        "task_kinds": case["task_kinds"],
        "language": case.get("language"),
        "paper": {
            "file": doc.get("file"),
            "sha256": doc.get("meta", {}).get("sha256"),
            "pages": len(doc.get("pages", [])),
            "front_matter": doc.get("front_matter", {}),
        },
        "paper_card": card,
        "sections": notes,
        "knowledge_points": points,
        "key_points": [kp for note in notes for kp in note["key_points"]][:12],
        "anchors": factory.items,
        "uncertainty": [],
        "provenance": {
            "extractor": doc.get("tier"),
            "body_size": doc.get("body_size"),
            "warnings": doc.get("warnings", []),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "script": "pdfx.py + compose.py",
            "tier_note": {
                "pymupdf": "block/line/char geometry available; paragraph bboxes anchor every quote",
                "pdftotext": "text only; anchors fall back to page-level containment",
                "ocr": "OCR text is approximate; anchors are page-level and wording may drift",
            }.get(doc.get("tier"), ""),
        },
        "change_log": [
            {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "what": "extractive baseline built from the PDF",
             "why": "guarantees an honest, anchored deliverable before any refinement"},
        ],
    }
    if unanchored:
        result["uncertainty"].append({
            "kind": "unanchored_claims",
            "detail": f"{len(unanchored)} refined statement(s) carry no verbatim evidence",
            "items": unanchored[:10],
        })
    result["uncertainty"].extend(_declared_uncertainty(judgments))
    if doc.get("status") != "ok":
        result["status"] = "partial"
        result["uncertainty"].append({
            "kind": "extraction",
            "detail": f"extractor reported status={doc.get('status')}",
            "warnings": doc.get("warnings"),
        })
    if doc.get("status") == "unreadable" or (not result["sections"] and not result["anchors"]):
        result["status"] = "unanswerable"
        result["reason"] = "the PDF exposes no extractable text layer"
        result["handoff"] = {
            "needs": "OCR or manual reading",
            "pages": len(doc.get("pages", [])),
            "suggestion": "run OCR (tesseract with chi_sim+eng) on each page, then re-run notes.py run",
        }
        result["uncertainty"].append({
            "kind": "blocked",
            "detail": result["reason"],
            "handoff": result["handoff"],
        })
    result["notes_markdown"] = render_markdown(result)
    return result


def _field_value(raw):
    if isinstance(raw, dict):
        return raw.get("text") or raw.get("value"), raw.get("evidence") or []
    return raw, []


def _apply_judgments(judgments, notes, card, points, factory, doc, unanchored):
    by_id = {n["id"]: n for n in notes}
    for section_id, patch in (judgments.get("sections") or {}).items():
        note = by_id.get(section_id)
        if not note or not isinstance(patch, dict):
            continue
        for key in ("objective", "conclusion"):
            if key in patch:
                value, evidence = _field_value(patch[key])
                note[key] = value
                note["extractive"] = False
                if evidence:
                    note["evidence"].extend(a["id"] for a in _anchors_for(evidence, doc, factory, section_id))
                elif value:
                    unanchored.append(f"{section_id}.{key}")
        for key in ("key_points", "methods", "results", "limitations"):
            if key in patch and isinstance(patch[key], list):
                values, evids = [], []
                for item in patch[key]:
                    value, evidence = _field_value(item)
                    if value:
                        values.append(value)
                    evids.extend(evidence)
                    if value and not evidence:
                        unanchored.append(f"{section_id}.{key}")
                note[key] = values
                note["extractive"] = False
                if evids:
                    note["evidence"].extend(a["id"] for a in _anchors_for(evids, doc, factory, section_id))
        note["anchors"] = list(dict.fromkeys(note["evidence"]))

    card_patch = judgments.get("paper_card") or {}
    list_fields = {"data", "methods", "findings", "limitations", "conclusions"}
    for key, raw in card_patch.items():
        value, evidence = _field_value(raw)
        if value is None:
            continue
        if key in list_fields and isinstance(value, str):
            value = [value]
        card[key] = value
        if isinstance(raw, dict) and raw.get("kind"):
            card["limitations_kind" if key == "limitations" else f"{key}_kind"] = raw["kind"]
        if evidence:
            card.setdefault("_anchors", []).extend(a["id"] for a in _anchors_for(evidence, doc, factory, "front"))
        elif isinstance(value, str) and len(value) > 40:
            unanchored.append(f"paper_card.{key}")

    for raw in judgments.get("knowledge_points") or []:
        term = raw.get("term")
        statement = raw.get("statement")
        if not term:
            continue
        evidence = raw.get("evidence") or []
        anchor_ids = [a["id"] for a in _anchors_for(evidence, doc, factory, "front")] if evidence else []
        points.append({
            "id": f"K{len(points) + 1:03d}",
            "term": term,
            "canonical": term.strip().lower(),
            "kind": raw.get("kind", "concept"),
            "statement": statement,
            "aliases": raw.get("aliases", []),
            "section": raw.get("section"),
            "page": raw.get("page"),
            "confidence": raw.get("confidence", 0.7),
            "anchor": anchor_ids[0] if anchor_ids else None,
            "origin": "judgment",
        })
        if not anchor_ids:
            unanchored.append(f"knowledge_points.{term}")

def _declared_uncertainty(judgments) -> list[dict]:
    out = []
    for item in (judgments or {}).get("uncertainty") or []:
        if isinstance(item, str) and item.strip():
            out.append({"kind": "declared", "detail": item.strip()})
        elif isinstance(item, dict) and item.get("detail"):
            out.append({"kind": item.get("kind", "declared"), "detail": item["detail"]})
    return out


def _anchors_for(pids, doc, factory, section_id):
    out = []
    for pid in pids or []:
        para = find_paragraph(doc, pid)
        if not para:
            continue
        anchor = factory.add(doc, para, 0, section_id, origin="judgment")
        out.append(anchor)
    return out


# --------------------------------------------------------------------------
# markdown rendering
# --------------------------------------------------------------------------

def _cite(anchors_by_id, ids):
    parts = []
    for aid in ids or []:
        anchor = anchors_by_id.get(aid)
        if anchor:
            parts.append(f"p.{anchor['page']}")
    return f" [{', '.join(parts)}]" if parts else ""


def render_markdown(result: dict) -> str:
    card = result["paper_card"]
    anchors_by_id = {a["id"]: a for a in result.get("anchors", [])}
    lines = []
    if result.get("status") == "unanswerable":
        lines.append("# 无法完成笔记")
        lines.append("")
        lines.append(f"**运行状态：** unanswerable")
        lines.append(f"**原因：** {result.get('reason') or '输入材料不可读'}")
        handoff = result.get("handoff") or {}
        if handoff:
            lines.append(f"**人工接管：** {handoff.get('needs')}；建议 {handoff.get('suggestion')}")
        lines.append("")
        for item in result.get("uncertainty", []):
            lines.append(f"- **{item.get('kind')}**: {item.get('detail')}")
        return "\n".join(lines) + "\n"
    title = card.get("title") or result["paper"].get("file") or "Paper"
    lines.append(f"# {title}")
    lines.append("")
    meta = []
    if card.get("authors"):
        meta.append("**Authors:** " + ", ".join(card["authors"][:8]))
    if card.get("pages"):
        meta.append(f"**Pages:** {card['pages']}")
    if card.get("paper_type"):
        meta.append(f"**Type:** {card['paper_type']}")
    if result.get("case_id"):
        meta.append(f"**Case:** {result['case_id']}")
    lines.extend(["  \n".join(meta), ""])

    if card.get("summary"):
        lines += ["## 一页摘要", "", card["summary"] + _cite(anchors_by_id, card.get("_anchors")), ""]

    lines += ["## 论文卡片", "", "| 字段 | 内容 |", "| --- | --- |"]
    rows = [
        ("研究问题", card.get("research_question")),
        ("数据", "; ".join(card.get("data") or []) or None),
        ("方法", "; ".join(card.get("methods") or []) or None),
        ("主要发现", "; ".join(card.get("findings") or []) or None),
        ("局限", "; ".join(card.get("limitations") or []) or card.get("limitations_note")),
    ]
    for label, value in rows:
        if value:
            lines.append(f"| {label} | {value} |")
    lines.append("")

    lines += ["## 章节地图", "", "| 节 | 标题 | 层级 | 页码 | 段数 | 状态 |", "| --- | --- | --- | --- | --- | --- |"]
    for note in result["sections"]:
        lines.append(
            f"| {note['id']} | {note['title']} | L{note['level']} | "
            f"p.{note['page_start']}–{note['page_end']} | {note.get('n_paragraphs', 0)} | {note['status']} |"
        )
    lines.append("")

    lines += ["## 章节笔记", ""]
    for note in result["sections"]:
        heading = note["title"] or note["id"]
        lines.append(f"### {note['id']} · {heading}")
        lines.append(f"*p.{note['page_start']}–{note['page_end']} · {note['n_paragraphs']} 段 · 状态 {note['status']}*")
        lines.append("")
        shown: set[str] = set()

        def emit(label: str, text: str, cite_ids=None) -> None:
            key = re.sub(r"\s+", " ", (text or "")).strip().lower()[:180]
            if not key or key in shown:
                return
            shown.add(key)
            suffix = _cite(anchors_by_id, cite_ids or []) if cite_ids else ""
            lines.append(f"- **{label}:** {text}{suffix}")

        emit("本节目的", note.get("objective") or "", note["anchors"][:1])
        if note.get("methods"):
            emit("方法", " ".join(note["methods"]))
        if note.get("results"):
            emit("结果", " ".join(note["results"]))
        emit("结论", note.get("conclusion") or "")
        if note.get("limitations"):
            emit("局限", " ".join(note["limitations"]))
        cont = note.get("continuity") or {}
        if cont.get("previous_tail") and cont.get("link") != "start":
            lines.append(f"- **承接:** 上一节以「{_short(cont['previous_tail'])}」收束，本节以「{_short(cont['opens_with'])}」展开。")
        for point in note.get("key_points", [])[:4]:
            emit("要点", point)
        lines.append("")

    if result.get("knowledge_points"):
        lines += ["## 知识点", "", "| 编号 | 术语 | 类型 | 说明 | 页码 |", "| --- | --- | --- | --- | --- |"]
        for kp in result["knowledge_points"][:60]:
            statement = (kp.get("statement") or "").replace("|", "/")
            lines.append(f"| {kp['id']} | {kp.get('term')} | {kp.get('kind')} | {statement[:140]} | p.{kp.get('page')} |")
        lines.append("")

    if result.get("uncertainty"):
        lines += ["## 不确定与未报告", ""]
        for item in result["uncertainty"]:
            lines.append(f"- **{item.get('kind')}**: {item.get('detail')}")
        lines.append("")

    ver = result.get("verification") or {}
    if result.get("anchors"):
        lines += ["## 锚点索引（可回链）", "", "| 锚点 | 页 | 节 | 引文（逐字） |", "| --- | --- | --- | --- |"]
        for anchor in result["anchors"][:40]:
            quote = (anchor.get("quote") or "").replace("|", "/")
            mark = "" if anchor.get("verified") else " ⚠"
            lines.append(f"| {anchor['id']}{mark} | p.{anchor.get('page')} | {anchor.get('section','')} | {_short(quote, 70)} |")
        if len(result["anchors"]) > 40:
            lines.append(f"| … | | | 其余 {len(result['anchors']) - 40} 条见 anchors.jsonl |")
        lines.append("")
    if ver:
        lines += [
            "## 核验",
            "",
            f"- 锚点总数 {ver.get('anchors_total')}，通过 {ver.get('anchors_verified')}，"
            f"失败 {ver.get('anchors_failed')}，覆盖率 {ver.get('coverage')}",
            f"- 核验方式: {ver.get('method')}",
            "",
        ]
    return "\n".join(lines)


def _short(text: str, limit: int = 60) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"
