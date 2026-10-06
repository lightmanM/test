"""Keys for the Google relay (``services/google_relay.py``): one per n8n deployment.

The key goes into the deployment's n8n credential; the deployment's refs keep only its SHA-256.
"""

from __future__ import annotations

import hashlib
import secrets

RELAY_PATH = "/api/google-relay"
KEY_REF = "google_relay_sha256"  # in the deployment's refs


def new_key(deployment_id: int) -> tuple[str, str]:
    """(the key for n8n, the digest kept in the deployment's refs)."""
    key = f"{deployment_id}.{secrets.token_urlsafe(32)}"
    return key, digest(key)


def digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()
