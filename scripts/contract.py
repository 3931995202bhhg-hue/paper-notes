#!/usr/bin/env python3
"""contract -- read the case directory and the requested output contract.

The platform hands each case a `case.json` plus `task.md` and the real paper
that must be read.  Nothing is assumed about either file: the source of the
paper, the requested task kind and the expected JSON fields are all detected,
and anything that cannot be found is reported instead of invented.

`load(case_dir)` returns:

    {
      "case_id": str,
      "task_text": str,
      "task_kinds": ["summarize", ...],
      "language": "en" | "zh",
      "papers": [{"path": ..., "role": ...}],
      "contract": {"fields": [{"name","type","required","description"}],
                   "source": "case.json|task.md|inferred", "raw": ...},
      "output_dir": str,
      "notes": [ ... things the skill could not resolve ... ]
    }
"""

from __future__ import annotations

import json
import os
import re
import unicodedata

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")

TASK_HINTS = {
    "translate": ("翻译", "translate", "译文", "translation"),
    "qa": ("question", "回答", "问答", "answer the following", "问题", "q&a"),
    "verify": ("核验", "校验", "verify", "check the claim", "fact-check", "核对"),
    "extract": ("参数", "抽取", "extract", "structured extraction", "字段"),
    "knowledge": ("知识点", "knowledge point", "概念", "术语"),
    "notes": ("笔记", "note", "summar", "总结", "摘要", "章节"),
}

# field name -> dotted path inside our canonical result
FIELD_ALIASES = {
    "case_id": "case_id",
    "status": "status",
    "sections": "sections",
    "section_notes": "sections",
    "chapter_notes": "sections",
    "summary": "paper_card.summary",
    "abstract_summary": "paper_card.summary",
    "overview": "paper_card.summary",
    "paper_card": "paper_card",
    "card": "paper_card",
    "knowledge_points": "knowledge_points",
    "concepts": "knowledge_points",
    "terms": "knowledge_points",
    "key_points": "key_points",
    "findings": "paper_card.findings",
    "results": "paper_card.findings",
    "method": "paper_card.methods",
    "methods": "paper_card.methods",
    "data": "paper_card.data",
    "research_question": "paper_card.research_question",
    "limitations": "paper_card.limitations",
    "conclusion": "paper_card.conclusions",
    "conclusions": "paper_card.conclusions",
    "evidence": "anchors",
    "anchors": "anchors",
    "sources": "anchors",
    "citations": "anchors",
    "uncertainty": "uncertainty",
    "uncertainties": "uncertainty",
    "provenance": "provenance",
    "change_log": "change_log",
    "notes": "notes_markdown",
    "markdown": "notes_markdown",
    "figures": "objects.figures",
    "tables": "objects.tables",
    "references": "paper_card.references",
}


def _read_text(path: str) -> str:
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as fh:
                return fh.read()
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


def _load_json(path: str):
    text = _read_text(path)
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # tolerate trailing commas / comments lightly
        cleaned = re.sub(r"//[^\n]*", "", text)
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


def _norm_field_name(name: str) -> str:
    n = unicodedata.normalize("NFKC", name or "").strip().lower()
    n = re.sub(r"[^a-z0-9]+", "_", n).strip("_")
    return n


def _contract_from(obj) -> list[dict]:
    """Normalise the many shapes an output contract can take."""
    fields: list[dict] = []

    def push(name, typ="string", required=True, desc=""):
        if not isinstance(name, str) or not name.strip():
            return
        fields.append(
            {
                "name": name.strip(),
                "key": _norm_field_name(name),
                "type": typ or "string",
                "required": bool(required),
                "description": (desc or "")[:400],
            }
        )

    if obj is None:
        return fields
    if isinstance(obj, str):
        for token in re.split(r"[,;\n]", obj):
            push(token)
        return fields
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, str):
                push(item)
            elif isinstance(item, dict):
                push(item.get("name") or item.get("field") or item.get("key"),
                     item.get("type", "string"),
                     item.get("required", True),
                     item.get("description", ""))
        return fields
    if isinstance(obj, dict):
        # {"fields": [...]} / {"required": [...]} / {name: {...}} / json-schema
        for wrapper in ("fields", "required_fields", "outputs", "expected_outputs", "columns"):
            if isinstance(obj.get(wrapper), list):
                return _contract_from(obj[wrapper])
        if isinstance(obj.get("properties"), dict):
            req = obj.get("required") or []
            for name, spec in obj["properties"].items():
                spec = spec if isinstance(spec, dict) else {}
                push(name, spec.get("type", "string"), name in req or not req, spec.get("description", ""))
            return fields
        if isinstance(obj.get("required"), list):
            for name in obj["required"]:
                push(name)
            if fields:
                return fields
        for name, spec in obj.items():
            if isinstance(spec, dict):
                push(name, spec.get("type", "string"), spec.get("required", True), spec.get("description", ""))
            elif isinstance(spec, str):
                push(name, "string", True, spec)
        return fields
    return fields


def _find_papers(case_dir: str, case: dict) -> list[dict]:
    papers: list[dict] = []
    candidates: list[str] = []

    def add(value):
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, list):
            for v in value:
                add(v)
        elif isinstance(value, dict):
            for key in ("path", "file", "pdf", "filename", "uri"):
                if isinstance(value.get(key), str):
                    candidates.append(value[key])

    if isinstance(case, dict):
        for key in ("paper", "papers", "input", "inputs", "files", "materials", "attachments", "pdf", "document"):
            if key in case:
                add(case[key])

    for cand in candidates:
        p = cand if os.path.isabs(cand) else os.path.join(case_dir, cand)
        if os.path.isfile(p) and p.lower().endswith(".pdf"):
            papers.append({"path": os.path.abspath(p), "role": "declared"})

    if not papers:
        for root, _dirs, files in os.walk(case_dir):
            for name in files:
                if name.lower().endswith(".pdf"):
                    papers.append({"path": os.path.abspath(os.path.join(root, name)), "role": "scanned"})
    # de-duplicate, keep stable order
    seen, uniq = set(), []
    for p in papers:
        if p["path"] in seen:
            continue
        seen.add(p["path"])
        uniq.append(p)
    return uniq


def load(case_dir: str) -> dict:
    case_dir = os.path.abspath(case_dir)
    notes: list[str] = []
    case = None
    for name in ("case.json", "input.json", "case.yaml", "task.json"):
        p = os.path.join(case_dir, name)
        if os.path.isfile(p):
            case = _load_json(p) if p.endswith(".json") else None
            if case is not None:
                break
    if case is None:
        notes.append("no machine-readable case.json found in the case directory")

    task_text = ""
    for name in ("task.md", "TASK.md", "task.txt", "README.md", "prompt.md"):
        p = os.path.join(case_dir, name)
        if os.path.isfile(p):
            task_text = _read_text(p)
            break
    if not task_text:
        notes.append("no task.md found; the requested task kind was inferred from the paper")

    case_id = None
    if isinstance(case, dict):
        for key in ("case_id", "caseId", "id", "task_id", "challenge_id"):
            if isinstance(case.get(key), str) and case[key].strip():
                case_id = case[key].strip()
                break
    if not case_id:
        case_id = os.path.basename(case_dir.rstrip("\\/")) or "case"
        notes.append(f"case_id not declared; used the directory name ({case_id})")

    contract_raw = None
    contract_source = None
    if isinstance(case, dict):
        for key in ("output_contract", "outputContract", "contract", "expected_outputs", "result_schema"):
            if key in case and case[key]:
                contract_raw = case[key]
                contract_source = f"case.json:{key}"
                break
    if contract_raw is None and task_text:
        m = re.search(r"(?:##+\s*)?(?:output\s+contract|输出契约|输出字段|交付字段|output fields?)(.{0,2000})", task_text, re.I | re.S)
        if m:
            block = m.group(1)
            names = re.findall(r"[-*`]\s*`?([A-Za-z_][A-Za-z0-9_\-]{1,40})`?\s*[:：]", block)
            if names:
                contract_raw = {"fields": [{"name": n} for n in names]}
                contract_source = "task.md"
    fields = _contract_from(contract_raw)
    if not fields:
        contract_source = "inferred"
        notes.append("no output contract declared; emitted the canonical schema and marked fields as inferred")

    joined = task_text.lower()
    kinds = [kind for kind, hints in TASK_HINTS.items() if any(h in joined for h in hints)]
    if not kinds:
        kinds = ["notes"]

    cjk = len(CJK_RE.findall(task_text))
    language = "zh" if cjk > max(20, 0.05 * max(1, len(task_text))) else "en"
    if not task_text:
        language = "unknown"

    return {
        "case_dir": case_dir,
        "case_id": case_id,
        "case": case,
        "task_text": task_text,
        "task_kinds": kinds,
        "language": language,
        "papers": _find_papers(case_dir, case if isinstance(case, dict) else {}),
        "contract": {"fields": fields, "source": contract_source, "raw": contract_raw},
        "notes": notes,
    }


def resolve_path(result: dict, dotted: str):
    cur = result
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None, False
    return cur, True


def apply_contract(result: dict, fields: list[dict]) -> dict:
    """Ensure every declared field exists at the top level of `result`."""
    satisfied, missing, inferred = [], [], []
    for field in fields:
        name = field["name"]
        if name in result and (result[name] not in (None, "") or isinstance(result[name], (list, dict))):
            satisfied.append(name)
            continue
        alias = FIELD_ALIASES.get(field["key"])
        value, found = (None, False)
        if alias:
            value, found = resolve_path(result, alias)
        if not found:
            # last resort: match a known top-level key by name similarity
            import difflib

            best = difflib.get_close_matches(field["key"], list(result.keys()), n=1, cutoff=0.72)
            if best:
                value, found = result[best[0]], True
        if found and value not in (None, "", [], {}):
            result[name] = value
            if name not in result.get("output_contract", {}).get("satisfied", []):
                inferred.append(name)
        else:
            result.setdefault(name, None)
            missing.append(name)
    result["output_contract"] = {
        "source": None,
        "declared": [f["name"] for f in fields],
        "satisfied": satisfied + inferred,
        "missing": missing,
        "notes": "fields not declared by the case are filled from the canonical schema"
        if not fields
        else "missing fields could not be grounded in the paper",
    }
    return result
