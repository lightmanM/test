"""Signed cookies and tokens (itsdangerous)."""

from __future__ import annotations

import hmac
from typing import Any

from itsdangerous import BadSignature, URLSafeTimedSerializer

SESSION_COOKIE = "wd_session"
ADMIN_COOKIE = "wd_admin"


class Signer:
    def __init__(self, secret: str) -> None:
        self._secret = secret

    def dumps(self, data: Any, purpose: str) -> str:
        return URLSafeTimedSerializer(self._secret, salt=purpose).dumps(data)

    def loads(self, token: str | None, purpose: str, max_age_seconds: int) -> Any | None:
        """Return the payload, or None if the token is missing, forged or expired."""
        if not token:
            return None
        try:
            return URLSafeTimedSerializer(self._secret, salt=purpose).loads(token, max_age=max_age_seconds)
        except BadSignature:  # includes SignatureExpired
            return None


def passcode_matches(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode(), expected.encode())
