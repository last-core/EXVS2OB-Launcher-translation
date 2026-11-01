"""Minimal PE / CLI metadata reader for embedded .NET assemblies.

The launcher EXE is a small native host with one or more complete .NET
assemblies appended to it. Every section's PointerToRawData is relative to the
start of *that* PE image, so all offsets are resolved against the image base
found while scanning for MZ headers.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

DIR_COM_DESCRIPTOR = 14


def u16(buf: bytes, off: int) -> int:
    return struct.unpack_from("<H", buf, off)[0]


def u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def u64(buf: bytes, off: int) -> int:
    return struct.unpack_from("<Q", buf, off)[0]


@dataclass
class Section:
    name: str
    virtual_address: int
    virtual_size: int
    raw_pointer: int
    raw_size: int


@dataclass
class DotNetImage:
    base: int                      # file offset where this PE image starts
    pe_offset: int                 # file offset of "PE\0\0"
    sections: List[Section]
    cli_offset: int                # file offset of the CLI header
    metadata_offset: int           # file offset of the metadata root (BSJB)
    metadata_size: int
    resources_offset: int          # file offset of the resources directory
    resources_size: int
    streams: Dict[str, Tuple[int, int]] = field(default_factory=dict)

    def rva_to_offset(self, rva: int) -> Optional[int]:
        for s in self.sections:
            span = max(s.virtual_size, s.raw_size)
            if s.virtual_address <= rva < s.virtual_address + span:
                return self.base + s.raw_pointer + (rva - s.virtual_address)
        return None

    @property
    def us(self) -> Tuple[int, int]:
        return self.streams["#US"]

    @property
    def strings(self) -> Tuple[int, int]:
        return self.streams["#Strings"]


def _read_sections(data: bytes, base: int, pe: int, num_sections: int,
                   optional_size: int) -> List[Section]:
    out = []
    table = pe + 24 + optional_size
    for i in range(num_sections):
        p = table + i * 40
        name = data[p:p + 8].rstrip(b"\0").decode("latin-1")
        vsize, vaddr, rsize, rptr = struct.unpack_from("<IIII", data, p + 8)
        out.append(Section(name, vaddr, vsize, rptr, rsize))
    return out


def find_candidates(data: bytes) -> List[int]:
    """Every offset whose header looks like a PE image (MZ + valid e_lfanew)."""
    found = []
    pos = 0
    while True:
        pos = data.find(b"MZ", pos)
        if pos < 0:
            return found
        try:
            lfanew = u32(data, pos + 0x3C)
            if 0x40 <= lfanew < 0x1000 and data[pos + lfanew:pos + lfanew + 4] == b"PE\0\0":
                found.append(pos)
        except struct.error:
            pass
        pos += 1


def parse_image(data: bytes, base: int) -> Optional[DotNetImage]:
    lfanew = u32(data, base + 0x3C)
    pe = base + lfanew
    if data[pe:pe + 4] != b"PE\0\0":
        return None
    num_sections = u16(data, pe + 6)
    optional_size = u16(data, pe + 20)
    opt = pe + 24
    magic = u16(data, opt)
    is_plus = magic == 0x20B
    if magic not in (0x10B, 0x20B):
        return None
    dirs = opt + (112 if is_plus else 96)
    n_dirs = u32(data, dirs - 4)
    if n_dirs <= DIR_COM_DESCRIPTOR:
        return None
    cli_rva = u32(data, dirs + DIR_COM_DESCRIPTOR * 8)
    if cli_rva == 0:
        return None
    sections = _read_sections(data, base, pe, num_sections, optional_size)
    img = DotNetImage(base=base, pe_offset=pe, sections=sections, cli_offset=0,
                      metadata_offset=0, metadata_size=0, resources_offset=0,
                      resources_size=0)
    cli = img.rva_to_offset(cli_rva)
    if cli is None or data[cli:cli + 4] != b"\x48\x00\x00\x00"[:4]:
        # cb is usually 0x48 but do not hard-fail on it
        if cli is None:
            return None
    md_rva, md_size = u32(data, cli + 8), u32(data, cli + 12)
    res_rva, res_size = u32(data, cli + 24), u32(data, cli + 28)
    md = img.rva_to_offset(md_rva)
    if md is None or data[md:md + 4] != b"BSJB":
        return None
    img.cli_offset = cli
    img.metadata_offset = md
    img.metadata_size = md_size
    res = img.rva_to_offset(res_rva) if res_rva else None
    img.resources_offset = res or 0
    img.resources_size = res_size
    img.streams = _read_streams(data, md)
    return img


def _read_streams(data: bytes, md: int) -> Dict[str, Tuple[int, int]]:
    version_len = u32(data, md + 12)
    pos = md + 16 + version_len
    pos += 2                      # flags
    count = u16(data, pos)
    pos += 2
    streams: Dict[str, Tuple[int, int]] = {}
    for _ in range(count):
        off, size = u32(data, pos), u32(data, pos + 4)
        pos += 8
        end = data.find(b"\0", pos)
        name = data[pos:end].decode("latin-1")
        pos = (end + 1 + 3) & ~3
        streams[name] = (md + off, size)
    return streams


def find_dotnet_images(data: bytes) -> List[DotNetImage]:
    images = []
    for base in find_candidates(data):
        try:
            img = parse_image(data, base)
        except Exception:
            img = None
        if img is not None:
            images.append(img)
    return images


def looks_like_text(s: str) -> bool:
    if not s or not s.strip():
        return False
    printable = sum(1 for c in s if c.isprintable() or c in "\r\n\t")
    return printable / len(s) > 0.9
