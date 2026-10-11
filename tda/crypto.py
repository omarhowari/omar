"""Optional AES-256-GCM encryption with a key derived from a shared network password.

Every packet (UDP and TCP frames) is prefixed with one marker byte:
  b"P" + plaintext                      when no password is configured
  b"E" + 12-byte nonce + ciphertext     when a password is configured
A client with a password refuses plaintext packets, and peers with a different
password simply cannot read each other (they stay invisible to one another).
"""
from __future__ import annotations

import os
from typing import Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_SALT = b"TDA-LAN-Messenger/v1"
_ITERATIONS = 200_000


class Cipher:
    def __init__(self, password: str = ""):
        self.enabled = bool(password)
        self._aes: Optional[AESGCM] = None
        if self.enabled:
            kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_SALT, iterations=_ITERATIONS)
            self._aes = AESGCM(kdf.derive(password.encode("utf-8")))

    def seal(self, data: bytes) -> bytes:
        if not self._aes:
            return b"P" + data
        nonce = os.urandom(12)
        return b"E" + nonce + self._aes.encrypt(nonce, data, None)

    def open(self, data: bytes) -> Optional[bytes]:
        if not data:
            return None
        tag, rest = data[:1], data[1:]
        if tag == b"P":
            return None if self._aes else rest
        if tag == b"E" and self._aes and len(rest) > 12:
            try:
                return self._aes.decrypt(rest[:12], rest[12:], None)
            except Exception:
                return None
        return None
