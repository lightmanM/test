"""Validate a user's settings form against the catalog's settings schema."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from workflow_demo.catalog.models import Setting, SettingType

SLACK_CHANNEL_ID = re.compile(r"^[CG][A-Z0-9]{6,}$")
MAX_URLS = 10


class SettingsError(ValueError):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


def _valid_url(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 500:
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_settings(schema: list[Setting], given: dict[str, Any]) -> dict[str, Any]:
    """Return cleaned settings (defaults applied) or raise SettingsError with per-field messages."""
    errors: dict[str, str] = {}
    cleaned: dict[str, Any] = {}
    unknown = set(given) - {s.key for s in schema}
    for key in sorted(unknown):
        errors[key] = "unknown setting"

    for setting in schema:
        value = given.get(setting.key, setting.default)
        if isinstance(value, str):
            value = value.strip()
        if value in (None, "", []):
            if setting.required:
                errors[setting.key] = "required"
            continue

        if setting.type is SettingType.STRING:
            if not isinstance(value, str) or len(value) > 200:
                errors[setting.key] = "must be text (max 200 characters)"
            elif value.startswith("="):  # n8n would evaluate it as an expression
                errors[setting.key] = "can't start with '='"
        elif setting.type is SettingType.NUMBER:
            if isinstance(value, bool) or not isinstance(value, int | float):
                errors[setting.key] = "must be a number"
        elif setting.type is SettingType.SELECT:
            if value not in (setting.options or []):
                errors[setting.key] = f"must be one of {setting.options}"
        elif setting.type is SettingType.URL_LIST:
            if not isinstance(value, list) or not 1 <= len(value) <= MAX_URLS:
                errors[setting.key] = f"must be a list of 1-{MAX_URLS} URLs"
            elif not all(_valid_url(v) for v in value):
                errors[setting.key] = "every entry must be an http(s) URL"
            else:
                value = [v.strip() for v in value]
        elif setting.type is SettingType.SLACK_CHANNEL:
            if not isinstance(value, str) or not SLACK_CHANNEL_ID.match(value):
                errors[setting.key] = "must be a Slack channel ID (e.g. C0123ABCD)"
        cleaned[setting.key] = value

    if errors:
        raise SettingsError(errors)
    return cleaned
