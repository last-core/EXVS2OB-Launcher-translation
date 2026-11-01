"""Read and rewrite the .NET user-string heap (#US).

Every blob:  <7-bit length n> <UTF-16LE data, n-1 bytes> <flag byte>
The length prefix counts the trailing flag byte, so rewriting a blob in place
keeps the heap layout valid as long as the payload byte length is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Optional

from .pe import DotNetImage


@dataclass
class UsBlob:
    prefix_offset: int   # absolute file offset of the length prefix
    prefix_length: int   # size of the length prefix in bytes
    payload_offset: int  # absolute file offset of the UTF-16 data
    payload_length: int  # byte length of the UTF-16 data (n-1)
    text: str
    flag: int

    @property
    def total_length(self) -> int:
        return self.prefix_length + self.payload_length + 1


def decode_compressed_int(buf, pos: int) -> tuple[int, int]:
    """ECMA-335 II.23.2 compressed unsigned integer (used by #US and #Blob).

    0x00-0x7F  1 byte,  0x80-0xBF  2 bytes,  0xC0-0xDF  4 bytes.
    """
    b0 = buf[pos]
    if b0 < 0x80:
        return b0, 1
    if b0 < 0xC0:
        return ((b0 & 0x3F) << 8) | buf[pos + 1], 2
    if b0 < 0xE0:
        return (((b0 & 0x1F) << 24) | (buf[pos + 1] << 16)
                | (buf[pos + 2] << 8) | buf[pos + 3]), 4
    raise ValueError(f"invalid compressed integer 0x{b0:02X}")


def encode_compressed_int(value: int) -> bytes:
    if value < 0x80:
        return bytes([value])
    if value < 0x4000:
        return bytes([0x80 | (value >> 8), value & 0xFF])
    if value < 0x20000000:
        return bytes([0xC0 | (value >> 24), (value >> 16) & 0xFF,
                      (value >> 8) & 0xFF, value & 0xFF])
    raise ValueError("value too large for compressed integer")


def decode_7bit_int(buf, pos: int) -> tuple[int, int]:
    """7-bit little-endian variable integer (BinaryWriter.Write7BitEncodedInt).

    Used by BAML record lengths.
    """
    value = 0
    shift = 0
    used = 0
    while True:
        b = buf[pos + used]
        used += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, used
        shift += 7
        if used > 5:
            raise ValueError("7-bit integer too long")


def encode_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def iter_blobs(data: bytes, image: DotNetImage) -> Iterator[UsBlob]:
    start, size = image.us
    end = start + size
    pos = 0
    while pos < size:
        try:
            n, pl = decode_compressed_int(data, start + pos)
        except (IndexError, ValueError):
            return
        if n == 0:                      # the mandatory leading empty string
            pos += pl
            continue
        payload = start + pos + pl
        payload_len = n - 1
        if payload + payload_len + 1 > end:
            return
        raw = data[payload:payload + payload_len]
        try:
            text = raw.decode("utf-16-le")
        except UnicodeDecodeError:
            text = raw.decode("utf-16-le", "replace")
        yield UsBlob(prefix_offset=start + pos, prefix_length=pl,
                     payload_offset=payload, payload_length=payload_len,
                     text=text, flag=data[payload + payload_len])
        pos += pl + n


def pad_to_bytes(text: str, byte_length: int) -> Optional[bytes]:
    """UTF-16LE encode and pad with spaces to exactly `byte_length` bytes."""
    raw = text.encode("utf-16-le")
    if len(raw) > byte_length:
        return None
    return raw + b" \x00" * ((byte_length - len(raw)) // 2)


def replace(data: bytearray, blob: UsBlob, text: str) -> bool:
    raw = pad_to_bytes(text, blob.payload_length)
    if raw is None:
        return False
    data[blob.payload_offset:blob.payload_offset + blob.payload_length] = raw
    return True
