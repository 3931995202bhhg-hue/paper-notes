#!/usr/bin/env python3
"""anchors -- every note item must be able to walk back to the page.

An anchor stores the smallest honest pointer available:

    page         1-based page number in the PDF
    pid          paragraph id produced by pdfx (p<page>_<n>)
    sentence     0-based sentence index inside that paragraph
    quote        verbatim substring of the paragraph, <= QUOTE_MAX chars
    bbox         rectangle on the page (PyMuPDF tier only)
    section      section id the paragraph belongs to

`verify()` re-opens the PDF and re-extracts the text *from the rectangle*
rather than trusting the pipeline's own paragraph text, so a wrong page or a
stale offset is caught instead of confirmed.
"""

from __future__ import annotations

import re

QUOTE_MAX = 220
_WS = re.compile(r"\s+")
_HYPHEN_BREAK = re.compile(r"-\s+")
_SOFT = "\u00ad"


def verify_key(text: str) -> str:
    """Normalisation used for anchor matching: insensitive to line breaks,
    end-of-line hyphenation and spacing, sensitive to wording."""
    t = (text or "").replace(_SOFT, "")
    t = _HYPHEN_BREAK.sub("", t)
    t = _WS.sub("", t)
    return t.lower()


def _squash_sentences(text: str) -> list[str]:
    from pdfx import has_cjk  # local import keeps the module standalone

    if has_cjk(text):
        parts = re.split(r"(?<=[。！？；])", text)
    else:
        parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def make_quote(paragraph: dict, sentence_index: int | None = None) -> tuple[str, int | None, bool]:
    """Return (quote, sentence_index, truncated) taken verbatim from `paragraph`."""
    text = paragraph["text"].strip()
    if sentence_index is not None:
        sentences = _squash_sentences(text)
        if 0 <= sentence_index < len(sentences):
            cand = sentences[sentence_index]
            if len(cand) <= QUOTE_MAX:
                return cand, sentence_index, False
            text = cand
    if len(text) <= QUOTE_MAX:
        return text, sentence_index, False
    cut = text[:QUOTE_MAX]
    # cut on a word boundary, never mid-token for latin scripts
    boundary = max(cut.rfind(" "), cut.rfind("。"), cut.rfind("．"), cut.rfind("；"))
    if boundary > QUOTE_MAX * 0.6:
        cut = cut[:boundary]
    return cut.strip(), sentence_index, True


def make_anchor(anchor_id: str, doc: dict, paragraph: dict, section_id: str,
                quote: str, sentence_index: int | None = None,
                kind: str = "text", truncated: bool = False, origin: str = "extractive") -> dict:
    return {
        "id": anchor_id,
        "pid": paragraph["id"],
        "page": paragraph["page"],
        "section": section_id,
        "sentence": sentence_index,
        "kind": kind,
        "quote": quote,
        "truncated": truncated,
        "bbox": paragraph.get("bbox"),
        "origin": origin,
        "verified": None,
        "verify_method": None,
        "char_offset": None,
    }


def _page_text(doc: dict, page_no: int) -> str:
    for page in doc.get("pages", []):
        if page["page"] == page_no:
            return page["text"]
    return ""


def _clip_text(fitz, pdf_path: str, page_no: int, bbox) -> str | None:
    if not bbox:
        return None
    try:
        with fitz.open(pdf_path) as pdf:
            page = pdf[page_no - 1]
            rect = fitz.Rect(*bbox)
            rect = rect & page.rect
            if rect.is_empty:
                return None
            return page.get_text("text", clip=rect)
    except Exception:
        return None


def verify(anchors: list[dict], doc: dict, pdf_path: str | None, strict: bool = True) -> dict:
    """Mark each anchor verified/unverified.  Never raises."""
    fitz = None
    if pdf_path:
        try:
            from pdfx import _fitz

            fitz = _fitz()
        except Exception:
            fitz = None

    total = len(anchors)
    ok = 0
    failed: list[dict] = []
    cache: dict[int, str] = {}
    for anchor in anchors:
        key = verify_key(anchor.get("quote") or "")
        if not key:
            anchor["verified"] = False
            anchor["verify_method"] = "empty_quote"
            failed.append({"id": anchor["id"], "reason": "empty_quote"})
            continue
        page_no = int(anchor.get("page") or 0)
        method = None
        hit = False
        if fitz is not None and anchor.get("bbox"):
            clipped = _clip_text(fitz, pdf_path, page_no, anchor["bbox"])
            if clipped and key in verify_key(clipped):
                hit, method = True, "bbox_clip"
        if not hit:
            if page_no not in cache:
                cache[page_no] = _page_text(doc, page_no)
            if key in verify_key(cache[page_no]):
                hit, method = True, "page_text"
        if not hit and strict and fitz is not None:
            # last chance: native text search for a short distinctive fragment
            try:
                with fitz.open(pdf_path) as pdf:
                    page = pdf[page_no - 1]
                    probe = (anchor.get("quote") or "")[:60]
                    if page.search_for(probe):
                        hit, method = True, "native_search"
            except Exception:
                pass
        anchor["verified"] = bool(hit)
        anchor["verify_method"] = method
        if hit:
            ok += 1
        else:
            failed.append({"id": anchor["id"], "page": page_no, "pid": anchor.get("pid"),
                           "reason": "quote not found on page"})
    return {
        "anchors_total": total,
        "anchors_verified": ok,
        "anchors_failed": total - ok,
        "coverage": round(ok / total, 4) if total else 0.0,
        "method": "bbox_clip+page_text+native_search" if fitz is not None else "page_text",
        "failures": failed[:40],
    }


def unanchored(items: list[dict]) -> list[dict]:
    return [i for i in items if not i.get("anchors")]
