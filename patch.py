#!/usr/bin/env python3
"""Translate the EXVS2OB launcher UI by patching its embedded .NET strings.

Usage:
    python patch.py scan   --exe EXVS2OB.exe --out scan.json
    python patch.py patch  --exe EXVS2OB.exe --out EXVS2OB_en.exe
    python patch.py verify --src EXVS2OB.exe --patched EXVS2OB_en.exe

The patcher never changes file size: every string is rewritten in place and
padded with spaces, so all heaps, offsets and the PE layout stay valid.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exvs2ob import pipeline


def cmd_scan(args) -> int:
    result = pipeline.scan(Path(args.exe))
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"#US CJK strings:   {len(result['us'])}")
        print(f"BAML CJK strings:  {len(result['baml'])}")
        print(f"written: {args.out}")
    else:
        print(text)
    return 0


def cmd_patch(args) -> int:
    data_dir = Path(args.data)
    report = pipeline.patch(Path(args.exe), Path(args.out), data_dir)
    print(report.summary())
    if report.too_long:
        print("\nTranslations that do not fit (need a shorter English string):")
        for orig, eng, need, have in report.too_long:
            print(f"  {orig!r} -> {eng!r} ({need} > {have} bytes)")
    if report.missing_us or report.missing_baml or report.missing_js:
        print("\nUntranslated strings found (add them to data/*.json):")
        for t in report.missing_us[:20]:
            print(f"  [us]   {t!r}")
        for t in report.missing_baml[:20]:
            print(f"  [baml] {t!r}")
        for t in report.missing_js[:20]:
            print(f"  [js]   {t!r}")
        return 1
    print(f"\nwritten: {args.out}")
    return 0


def cmd_verify(args) -> int:
    result = pipeline.verify(Path(args.src), Path(args.patched))
    print(f"same size:            {result['same_size']}")
    if "us_blob_count" in result:
        print(f"#US blobs:            {result['us_blob_count']}")
        print(f"residual CJK strings: {len(result['residual'])}")
        print(f"bytes changed outside known heaps: {result['stray_bytes_changed']}")
        for kind, text in result["residual"][:20]:
            print(f"  [{kind}] {text!r}")
    for problem in result["problems"]:
        print("PROBLEM:", problem)
    ok = (result["same_size"] and not result["problems"]
          and not result["residual"] and result["stray_bytes_changed"] == 0)
    print("\nOK" if ok else "\nFAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    here = Path(__file__).resolve().parent
    default_data = str(here / "data")

    s = sub.add_parser("scan", help="list untranslated CJK strings")
    s.add_argument("--exe", required=True)
    s.add_argument("--out")
    s.set_defaults(func=cmd_scan)

    p = sub.add_parser("patch", help="write a translated copy of the exe")
    p.add_argument("--exe", required=True, help="pristine launcher exe")
    p.add_argument("--out", required=True, help="output exe (never the input)")
    p.add_argument("--data", default=default_data, help="translation tables directory")
    p.set_defaults(func=cmd_patch)

    v = sub.add_parser("verify", help="check a patched exe")
    v.add_argument("--src", required=True, help="pristine launcher exe")
    v.add_argument("--patched", required=True, help="patched exe to check")
    v.set_defaults(func=cmd_verify)

    args = ap.parse_args(argv)
    if getattr(args, "out", None) and args.cmd == "patch":
        if Path(args.out).resolve() == Path(args.exe).resolve():
            ap.error("--out must differ from --exe (the original is never modified)")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
