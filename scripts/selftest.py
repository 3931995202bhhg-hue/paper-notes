#!/usr/bin/env python3
"""selftest -- structural check of a produced notes package.

    python3 scripts/selftest.py --out /app/output

Exits 0 only when the delivery is internally consistent: required keys exist,
every section points at real anchors, every anchor carries a quote and a
verdict, page ranges are ordered, and the declared contract is accounted for.

This checks *consistency*, not scholarship: a passing run says the notes are
well-formed and traceable, not that every reading is correct.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

REQUIRED_TOP = ("case_id", "status", "sections", "paper_card", "knowledge_points", "anchors")
SECTION_FIELDS = ("id", "title", "level", "page_start", "page_end", "status", "evidence")
ANCHOR_FIELDS = ("id", "page", "quote", "verified")


def check(out_dir: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    path = os.path.join(out_dir, "result.json")
    if not os.path.isfile(path):
        return [f"missing {path}"], warnings
    with open(path, "r", encoding="utf-8") as fh:
        result = json.load(fh)

    for key in REQUIRED_TOP:
        if key not in result:
            errors.append(f"result.{key} missing")

    status = result.get("status")
    if status not in ("success", "partial", "unanswerable"):
        errors.append(f"status '{status}' is not one of success|partial|unanswerable")

    anchors = result.get("anchors") or []
    anchor_ids = {a.get("id") for a in anchors}
    if len(anchor_ids) != len(anchors):
        errors.append("duplicate anchor ids")
    for anchor in anchors:
        for field in ANCHOR_FIELDS:
            if field not in anchor:
                errors.append(f"anchor {anchor.get('id')} missing {field}")
                break
        else:
            if not str(anchor.get("quote") or "").strip():
                errors.append(f"anchor {anchor.get('id')} has an empty quote")
            if anchor.get("verified") is None:
                errors.append(f"anchor {anchor.get('id')} was never verified")
            if not isinstance(anchor.get("page"), int) or anchor.get("page", 0) < 1:
                errors.append(f"anchor {anchor.get('id')} has an invalid page")

    seen_titles: dict[str, str] = {}
    for section in result.get("sections") or []:
        sid = section.get("id")
        for field in SECTION_FIELDS:
            if field not in section:
                errors.append(f"section {sid} missing {field}")
                break
        if section.get("page_start", 0) > section.get("page_end", 0):
            errors.append(f"section {sid} has page_start > page_end")
        for aid in section.get("evidence") or []:
            if aid not in anchor_ids:
                errors.append(f"section {sid} cites missing anchor {aid}")
        lvl = section.get("level")
        if not isinstance(lvl, int) or lvl < 1:
            errors.append(f"section {sid} has an invalid level")
        key = (section.get("title") or "").strip().lower()
        if key and key in seen_titles:
            warnings.append(f"section {sid} repeats the title of {seen_titles[key]}")
        seen_titles.setdefault(key, sid)
        if section.get("status") == "empty":
            warnings.append(f"section {sid} ({section.get('title')}) has no extractable body")

    verification = result.get("verification") or {}
    total = verification.get("anchors_total")
    ok = verification.get("anchors_verified")
    if total is not None and ok is not None and total >= ok:
        passed = verification.get("coverage")
        if passed is not None and total:
            expected = round(ok / total, 4)
            if abs(expected - passed) > 0.001:
                errors.append(f"verification.coverage {passed} != {expected}")
    if status == "success" and verification.get("anchors_failed"):
        errors.append("status=success but anchors failed verification")

    contract = result.get("output_contract") or {}
    if contract.get("missing"):
        if status == "success":
            errors.append(f"contract fields missing ({', '.join(contract['missing'])}) while status=success")
        else:
            warnings.append(f"contract fields unresolved: {', '.join(contract['missing'])}")

    for name in ("notes.md", "paper_card.json", "anchors.jsonl", "knowledge_points.csv", "manifest.json"):
        if not os.path.isfile(os.path.join(out_dir, name)):
            warnings.append(f"optional artifact missing: {name}")

    return errors, warnings


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="selftest.py")
    parser.add_argument("--out", default="/app/output")
    args = parser.parse_args(argv)
    errors, warnings = check(args.out)
    for warning in warnings:
        print(f"WARN  {warning}")
    for error in errors:
        print(f"FAIL  {error}")
    if errors:
        print(json.dumps({"ok": False, "errors": len(errors), "warnings": len(warnings)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "errors": 0, "warnings": len(warnings)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
