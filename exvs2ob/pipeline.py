"""Patch / scan / verify pipeline for the EXVS2OB launcher translation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import baml, pe, usheap

CJK_RANGES = (
    (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF),   # ideographs
    (0x3040, 0x30FF),                                        # kana
    (0x3005, 0x3007), (0x300C, 0x300D), (0x3010, 0x3011),    # CJK punctuation
)

# Wider class used when splitting CJK runs inside code strings; it matches the
# way the JS comment table was authored (full-width punctuation included).
WIDE_RANGES = CJK_RANGES + ((0x3000, 0x303F), (0xFF00, 0xFFEF))


def has_cjk(text: str) -> bool:
    return any(any(lo <= ord(c) <= hi for lo, hi in CJK_RANGES) for c in text)


def has_wide(text: str) -> bool:
    return any(any(lo <= ord(c) <= hi for lo, hi in WIDE_RANGES) for c in text)


def cjk_count(text: str) -> int:
    return sum(1 for c in text if any(lo <= ord(c) <= hi for lo, hi in CJK_RANGES))


def looks_like_code(text: str) -> bool:
    return "function(" in text or "document." in text or "=>" in text


@dataclass
class Report:
    us_applied: int = 0
    baml_applied: int = 0
    js_applied: int = 0
    missing_us: List[str] = field(default_factory=list)
    missing_baml: List[str] = field(default_factory=list)
    missing_js: List[str] = field(default_factory=list)
    too_long: List[Tuple[str, str, int, int]] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"#US strings patched:   {self.us_applied}",
                 f"BAML strings patched: {self.baml_applied}",
                 f"JS comment runs:      {self.js_applied}"]
        if self.missing_us:
            lines.append(f"untranslated #US strings: {len(self.missing_us)}")
        if self.missing_baml:
            lines.append(f"untranslated BAML strings: {len(self.missing_baml)}")
        if self.missing_js:
            lines.append(f"untranslated JS comment runs: {len(self.missing_js)}")
        if self.too_long:
            lines.append(f"translations too long: {len(self.too_long)}")
        return "\n".join(lines)


def load_tables(data_dir: Path) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    us = json.loads((data_dir / "us.json").read_text(encoding="utf-8"))["strings"]
    bm = json.loads((data_dir / "baml.json").read_text(encoding="utf-8"))["strings"]
    js = json.loads((data_dir / "js_comments.json").read_text(encoding="utf-8"))["comments"]
    return us, bm, js


def main_image(data: bytes) -> pe.DotNetImage:
    images = pe.find_dotnet_images(data)
    if not images:
        raise SystemExit("no embedded .NET assembly found - unsupported exe")
    preferred = [i for i in images if "#US" in i.streams and i.resources_offset]
    if not preferred:
        preferred = [i for i in images if "#US" in i.streams]
    if not preferred:
        raise SystemExit("no #US heap found in any embedded assembly")
    return max(preferred, key=lambda i: i.metadata_size)


def _translate_js(text: str, comments: Dict[str, str], report: Report) -> str:
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if has_wide(ch):
            j = i
            while j < len(text) and has_wide(text[j]):
                j += 1
            run = text[i:j]
            eng = comments.get(run)
            if eng is None:
                report.missing_js.append(run)
                out.append(run)
            else:
                out.append(eng + " " * (len(run) - len(eng)))
                report.js_applied += 1
            i = j
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def patch(src: Path, dst: Path, data_dir: Path) -> Report:
    us_table, baml_table, js_table = load_tables(data_dir)
    data = bytearray(src.read_bytes())
    image = main_image(data)
    report = Report()

    for blob in usheap.iter_blobs(data, image):
        text = blob.text
        if text in us_table:
            if usheap.replace(data, blob, us_table[text]):
                report.us_applied += 1
            else:
                need = len(us_table[text].encode("utf-16-le"))
                report.too_long.append((text, us_table[text], need, blob.payload_length))
        elif looks_like_code(text) and has_cjk(text):
            new = _translate_js(text, js_table, report)
            if not usheap.replace(data, blob, new):
                report.too_long.append((text[:40], new[:40], 0, blob.payload_length))
        elif has_cjk(text):
            report.missing_us.append(text)

    start, end = baml.region(data, image)
    if start:
        for s in baml.iter_strings(data, start, end):
            if s.text in baml_table:
                raw = baml.pad_to_bytes(baml_table[s.text], s.payload_length)
                if raw is None:
                    report.too_long.append((s.text, baml_table[s.text],
                                            len(baml_table[s.text].encode()),
                                            s.payload_length))
                    continue
                data[s.payload_offset:s.payload_offset + s.payload_length] = raw
                report.baml_applied += 1
            elif has_cjk(s.text):
                report.missing_baml.append(s.text)

    dst.write_bytes(bytes(data))
    return report


def scan(path: Path) -> dict:
    data = path.read_bytes()
    image = main_image(data)
    us_entries = []
    for blob in usheap.iter_blobs(data, image):
        if has_cjk(blob.text):
            us_entries.append({"text": blob.text,
                               "bytes": blob.payload_length,
                               "offset": hex(blob.payload_offset)})
    start, end = baml.region(data, image)
    baml_entries = []
    if start:
        for s in baml.iter_strings(data, start, end):
            if has_cjk(s.text):
                baml_entries.append({"text": s.text,
                                     "bytes": s.payload_length,
                                     "offset": hex(s.payload_offset)})
    return {"us": us_entries, "baml": baml_entries}


def verify(src: Path, patched: Path) -> dict:
    a = src.read_bytes()
    b = patched.read_bytes()
    result = {"same_size": len(a) == len(b), "problems": []}
    if not result["same_size"]:
        result["problems"].append(f"size changed: {len(a)} -> {len(b)}")
        return result

    data = b
    image = main_image(data)
    residual = []
    for blob in usheap.iter_blobs(data, image):
        if has_cjk(blob.text):
            residual.append(("us", blob.text))
    start, end = baml.region(data, image)
    if start:
        for s in baml.iter_strings(data, start, end):
            if has_cjk(s.text):
                residual.append(("baml", s.text))
    result["residual"] = residual

    us_start, us_size = image.us
    allowed = [(us_start, us_start + us_size), (start, end)]
    stray = 0
    for k in range(len(a)):
        if a[k] != b[k] and not any(lo <= k < hi for lo, hi in allowed if lo):
            stray += 1
    result["stray_bytes_changed"] = stray
    result["us_blob_count"] = sum(1 for _ in usheap.iter_blobs(data, image))
    return result
