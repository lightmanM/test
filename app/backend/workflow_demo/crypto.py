"""Encryption for secrets the demo stores itself (manual connectors such as a Meegle token).

AES-256-GCM with a random nonce; the associated data binds each ciphertext to its owner and
connector, so a value copied to another row fails to decrypt.
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = "v1"


class CryptoError(Exception):
    pass


class SecretBox:
    def __init__(self, key_b64: str) -> None:
        try:
            key = base64.b64decode(key_b64, validate=True)
        except (binascii.Error, ValueError):
            raise CryptoError("DATA_ENCRYPTION_KEY must be base64") from None
        if len(key) != 32:
            raise CryptoError("DATA_ENCRYPTION_KEY must decode to 32 bytes")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: str, context: str) -> str:
        nonce = os.urandom(12)
        sealed = self._aead.encrypt(nonce, plaintext.encode(), context.encode())
        return f"{VERSION}:{base64.b64encode(nonce + sealed).decode()}"

    def decrypt(self, token: str, context: str) -> str:
        version, _, payload = token.partition(":")
        if version != VERSION:
            raise CryptoError("unknown ciphertext version")
        raw = base64.b64decode(payload)
        try:
            return self._aead.decrypt(raw[:12], raw[12:], context.encode()).decode()
        except InvalidTag:
            raise CryptoError("ciphertext doesn't match its owner or key") from None
