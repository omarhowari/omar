"""Wire format for TCP connections.

frame   := uint32 big-endian length || sealed(payload)
payload := b"J" + UTF-8 JSON   (control messages)
         | b"B" + raw bytes    (file data chunks)
"""
from __future__ import annotations

import json
import re
import struct
from pathlib import PurePosixPath
from typing import Iterator, Tuple

from .crypto import Cipher

MAX_FRAME = 4 * 1024 * 1024
CHUNK_SIZE = 256 * 1024


class ProtocolError(Exception):
    pass


def encode_json(cipher: Cipher, obj: dict) -> bytes:
    body = cipher.seal(b"J" + json.dumps(obj, ensure_ascii=False).encode("utf-8"))
    return struct.pack(">I", len(body)) + body


def encode_bin(cipher: Cipher, data: bytes) -> bytes:
    body = cipher.seal(b"B" + data)
    return struct.pack(">I", len(body)) + body


class FrameBuffer:
    def __init__(self, cipher: Cipher):
        self.cipher = cipher
        self.buf = bytearray()

    def feed(self, data: bytes) -> None:
        self.buf += data

    def frames(self) -> Iterator[Tuple[str, object]]:
        while len(self.buf) >= 4:
            (n,) = struct.unpack(">I", self.buf[:4])
            if n == 0 or n > MAX_FRAME:
                raise ProtocolError("bad frame size")
            if len(self.buf) < 4 + n:
                return
            raw = bytes(self.buf[4:4 + n])
            del self.buf[:4 + n]
            plain = self.cipher.open(raw)
            if plain is None:
                raise ProtocolError("cannot decrypt (wrong network password?)")
            kind, body = plain[:1], plain[1:]
            if kind == b"J":
                obj = json.loads(body.decode("utf-8"))
                if not isinstance(obj, dict):
                    raise ProtocolError("bad json")
                yield "json", obj
            elif kind == b"B":
                yield "bin", body
            else:
                raise ProtocolError("unknown frame kind")


_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_relpath(rel: str) -> PurePosixPath:
    """Turn a remote-supplied relative path into a safe one (no traversal, no drive letters)."""
    parts = []
    for part in str(rel).replace("\\", "/").split("/"):
        part = _BAD_CHARS.sub("_", part).strip().rstrip(".")
        if part in ("", ".", ".."):
            continue
        if part.split(".")[0].upper() in _RESERVED:
            part = "_" + part
        parts.append(part[:200])
    if not parts:
        raise ProtocolError("empty path")
    return PurePosixPath(*parts)
