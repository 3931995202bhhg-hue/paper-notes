#!/usr/bin/env python3
"""notes -- the entry point of the 文献总结与结构化笔记 skill.

    python scripts/notes.py run --case-dir /input --out /app/output
    python scripts/notes.py run --case-dir /input --out /app/output --judgments judgments.json
    python scripts/notes.py extract --pdf paper.pdf --out extract.json
    python scripts/notes.py verify --out /app/output

`run` never depends on the model: it produces a complete, anchored baseline.
`judgments.json` (see references/judgment-schema.md) refines the wording while
keeping every refinement tied to evidence or explicitly marked unanchored.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import anchors as anchor_mod  # noqa: E402
import compose  # noqa: E402
import contract as contract_mod  # noqa: E402
import pdfx  # noqa: E402

SKILL_VERSION = "1.0.0"


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: str, payload) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _write_anchors_jsonl(path: str, anchors: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for anchor in anchors:
            fh.write(json.dumps(anchor, ensure_ascii=False) + "\n")


def _write_kp_csv(path: str, points: list[dict]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "term", "kind", "statement", "section", "page", "confidence", "anchor"])
        for kp in points:
            writer.writerow([
                kp.get("id"), kp.get("term"), kp.get("kind"), kp.get("statement"),
                kp.get("section"), kp.get("page"), kp.get("confidence"), kp.get("anchor"),
            ])


def run(case_dir: str, out_dir: str, judgments_path: str | None = None,
        max_pages: int | None = None, do_verify: bool = True) -> dict:
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    log: list[str] = []

    def say(msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        log.append(line)
        print(line, file=sys.stderr)

    case = contract_mod.load(case_dir)
    say(f"case_id={case['case_id']} papers={len(case['papers'])} task={case['task_kinds']}")

    judgments = None
    if judgments_path and os.path.isfile(judgments_path):
        with open(judgments_path, "r", encoding="utf-8") as fh:
            judgments = json.load(fh)
        say(f"judgments loaded: {judgments_path}")
    elif judgments_path:
        say(f"judgments path given but missing: {judgments_path}")

    if not case["papers"]:
        result = {
            "case_id": case["case_id"],
            "status": "unanswerable",
            "reason": "no PDF found in the case directory",
            "uncertainty": [{"kind": "input", "detail": "no paper material was provided"}],
            "task_kinds": case["task_kinds"],
            "sections": [],
            "paper_card": {},
            "knowledge_points": [],
            "anchors": [],
            "verification": {"anchors_total": 0, "anchors_verified": 0, "anchors_failed": 0, "coverage": 0.0},
            "provenance": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "skill_version": SKILL_VERSION},
            "change_log": case["notes"],
        }
        result["notes_markdown"] = f"# 无法解析输入\n\n{result['reason']}\n"
        contract_mod.apply_contract(result, case["contract"]["fields"])
        _write_json(os.path.join(out_dir, "result.json"), result)
        with open(os.path.join(out_dir, "notes.md"), "w", encoding="utf-8") as fh:
            fh.write(result["notes_markdown"])
        say("no paper: wrote an unanswerable result")
        return result

    pdf_path = case["papers"][0]["path"]
    say(f"pdf={pdf_path}")
    doc = pdfx.extract(pdf_path, max_pages=max_pages)
    say(f"extract tier={doc.get('tier')} pages={len(doc.get('pages', []))} "
        f"sections={len(doc.get('sections', []))} status={doc.get('status')}")

    result = compose.build(doc, case, judgments=judgments, pdf_path=pdf_path)

    if do_verify:
        summary = anchor_mod.verify(result["anchors"], doc, pdf_path)
        result["verification"] = summary
        say(f"verify anchors={summary['anchors_total']} ok={summary['anchors_verified']} "
            f"failed={summary['anchors_failed']} coverage={summary['coverage']}")
        if summary["anchors_failed"]:
            result["status"] = "partial"
            result["uncertainty"].append({
                "kind": "anchor_failures",
                "detail": f"{summary['anchors_failed']} anchor(s) did not resolve back to the page",
                "items": summary["failures"][:5],
            })
    else:
        result["verification"] = {"anchors_total": len(result["anchors"]), "skipped": True}

    if len(case["papers"]) > 1:
        result["uncertainty"].append({
            "kind": "input",
            "detail": f"{len(case['papers']) - 1} additional PDF(s) present but only the first was noted",
            "files": [os.path.basename(p["path"]) for p in case["papers"][1:]],
        })

    result.setdefault("provenance", {})["skill_version"] = SKILL_VERSION
    result["provenance"]["elapsed_s"] = round(time.time() - t0, 2)
    result["provenance"]["contract_source"] = case["contract"]["source"]
    contract_mod.apply_contract(result, case["contract"]["fields"])
    result["notes_markdown"] = compose.render_markdown(result)

    # ---- artifacts -------------------------------------------------------
    _write_json(os.path.join(out_dir, "result.json"), result)
    with open(os.path.join(out_dir, "notes.md"), "w", encoding="utf-8") as fh:
        fh.write(result["notes_markdown"])
    _write_json(os.path.join(out_dir, "paper_card.json"), result["paper_card"])
    _write_anchors_jsonl(os.path.join(out_dir, "anchors.jsonl"), result["anchors"])
    _write_kp_csv(os.path.join(out_dir, "knowledge_points.csv"), result["knowledge_points"])

    artifacts = []
    for name in ("result.json", "notes.md", "paper_card.json", "anchors.jsonl", "knowledge_points.csv"):
        path = os.path.join(out_dir, name)
        if os.path.isfile(path):
            artifacts.append({"path": name, "bytes": os.path.getsize(path), "sha256": _sha256(path)})
    _write_json(os.path.join(out_dir, "manifest.json"), {
        "skill": "paper-notes",
        "skill_version": SKILL_VERSION,
        "case_id": case["case_id"],
        "paper": {"file": os.path.basename(pdf_path), "sha256": doc.get("meta", {}).get("sha256"),
                  "pages": len(doc.get("pages", [])), "tier": doc.get("tier")},
        "contract": {"source": case["contract"]["source"], "declared": [f["name"] for f in case["contract"]["fields"]]},
        "artifacts": artifacts,
        "generated_at": result["provenance"]["generated_at"],
    })
    with open(os.path.join(out_dir, "run.log"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(log + case["notes"]) + "\n")

    say(f"done status={result['status']} sections={len(result['sections'])} "
        f"knowledge_points={len(result['knowledge_points'])}")
    return result


def verify_only(out_dir: str) -> dict:
    result_path = os.path.join(out_dir, "result.json")
    if not os.path.isfile(result_path):
        raise SystemExit(f"no result.json under {out_dir}")
    with open(result_path, "r", encoding="utf-8") as fh:
        result = json.load(fh)
    paper = result.get("paper", {}).get("file")
    candidates = [os.path.join(out_dir, paper or "")]
    # the original PDF is not copied into the output; verification needs it
    pdf_path = next((c for c in candidates if c and os.path.isfile(c)), None)
    if not pdf_path:
        raise SystemExit("original PDF not found next to the outputs; run `run` with --pdf available")
    summary = anchor_mod.verify(result["anchors"], {}, pdf_path)
    result["verification"] = summary
    _write_json(result_path, result)
    return summary


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="notes.py", description="chapter-aligned, anchored paper notes")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="extract a case and write notes")
    p_run.add_argument("--case-dir", default="/input")
    p_run.add_argument("--out", default="/app/output")
    p_run.add_argument("--judgments", default=None)
    p_run.add_argument("--max-pages", type=int, default=None)
    p_run.add_argument("--no-verify", action="store_true")

    p_ext = sub.add_parser("extract", help="only dump the layout-aware extraction")
    p_ext.add_argument("--pdf", required=True)
    p_ext.add_argument("--out", required=True)
    p_ext.add_argument("--max-pages", type=int, default=None)

    p_ver = sub.add_parser("verify", help="re-verify anchors of an existing result")
    p_ver.add_argument("--out", default="/app/output")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "run":
            result = run(args.case_dir, args.out, args.judgments, args.max_pages, not args.no_verify)
            print(json.dumps({
                "status": result["status"],
                "case_id": result["case_id"],
                "sections": len(result.get("sections", [])),
                "anchors": len(result.get("anchors", [])),
                "verification": result.get("verification", {}).get("coverage"),
                "out": args.out,
            }, ensure_ascii=False))
            return 0 if result["status"] in ("success", "partial") else 1
        if args.cmd == "extract":
            doc = pdfx.extract(args.pdf, max_pages=args.max_pages)
            _write_json(args.out, doc)
            print(json.dumps({"tier": doc.get("tier"), "sections": len(doc.get("sections", [])),
                              "pages": len(doc.get("pages", []))}, ensure_ascii=False))
            return 0 if doc.get("ok") else 1
        if args.cmd == "verify":
            print(json.dumps(verify_only(args.out), ensure_ascii=False))
            return 0
    except SystemExit:
        raise
    except Exception as exc:  # keep a machine-readable failure
        traceback.print_exc()
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
