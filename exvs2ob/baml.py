"""Locate and rewrite text literals inside compiled XAML (BAML) resources.

The launcher's BAML encodes every user-visible string as

    <compressed length N> <UTF-8 bytes> \\x99\\xFD

which can be rewritten in place while keeping the record stream valid, as long
as the replacement has the same byte length (pad with ASCII spaces).

Rather than parsing the whole BAML record grammar (fragile across compilers),
we scan for that three-part pattern and validate the UTF-8 payload.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List, Optional

from .usheap import decode_7bit_int as decode_varint

STRING_END = b"\x99\xfd"


@dataclass
class BamlString:
    payload_offset: int  # absolute file offset of the UTF-8 text
    payload_length: int  # byte length of the UTF-8 text
    text: str


def region(data: bytes, image) -> tuple[int, int]:
    """The managed-resources directory of `image`, skipping the length prefix."""
    start = image.resources_offset
    if start == 0:
        return 0, 0
    if data[start:start + 4] != (0xBEEFCACE).to_bytes(4, "little"):
        start += 4                       # int32 size prefix written by the compiler
    return start, start + max(0, image.resources_size - 4)


def iter_strings(data: bytes, start: int, end: int) -> Iterator[BamlString]:
    """Yield every BAML literal once, dropping fragments that begin inside a
    longer literal (the pattern scan can otherwise report mid-string hits)."""
    candidates = []
    pos = start
    while pos < end - 4:
        try:
            length, pl = decode_varint(data, pos)
        except (IndexError, ValueError):
            pos += 1
            continue
        payload = pos + pl
        stop = payload + length
        if 2 <= length <= 16384 and stop + 2 <= end and data[stop:stop + 2] == STRING_END:
            raw = data[payload:stop]
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = None
            if text and (text.isprintable() or all(
                    c.isprintable() or c in "\r\n\t" for c in text)):
                candidates.append(BamlString(payload, length, text))
        pos += 1

    candidates.sort(key=lambda s: (s.payload_offset, -s.payload_length))
    kept: List[BamlString] = []
    span_end = -1
    for s in candidates:
        if s.payload_offset < span_end:
            continue
        kept.append(s)
        span_end = s.payload_offset + s.payload_length
    return iter(kept)


def pad_to_bytes(text: str, byte_length: int) -> Optional[bytes]:
    raw = text.encode("utf-8")
    if len(raw) > byte_length:
        return None
    return raw + b" " * (byte_length - len(raw))
