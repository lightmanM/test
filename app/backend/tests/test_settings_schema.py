import pytest

from workflow_demo.catalog.models import Setting, SettingType
from workflow_demo.services.settings_schema import SettingsError, validate_settings

SCHEMA = [
    Setting(key="channel", label="Channel", type=SettingType.SLACK_CHANNEL),
    Setting(key="sites", label="Sites", type=SettingType.URL_LIST, default=["https://example.com"]),
    Setting(key="window", label="Window", type=SettingType.SELECT, options=[24, 720], default=24),
    Setting(key="name", label="Name", type=SettingType.STRING, required=False),
    Setting(key="count", label="Count", type=SettingType.NUMBER, required=False),
]


def test_defaults_applied_and_strings_trimmed():
    assert validate_settings(SCHEMA, {"channel": " C0123ABCD "}) == {
        "channel": "C0123ABCD",
        "sites": ["https://example.com"],
        "window": 24,
    }


@pytest.mark.parametrize(
    ("given", "field"),
    [
        ({}, "channel"),
        ({"channel": "general"}, "channel"),
        ({"channel": "C0123ABCD", "sites": ["ftp://x"]}, "sites"),
        ({"channel": "C0123ABCD", "sites": []}, "sites"),
        ({"channel": "C0123ABCD", "window": 5}, "window"),
        ({"channel": "C0123ABCD", "count": "3"}, "count"),
        ({"channel": "C0123ABCD", "count": True}, "count"),
        ({"channel": "C0123ABCD", "extra": 1}, "extra"),
    ],
)
def test_invalid_values(given, field):
    with pytest.raises(SettingsError) as info:
        validate_settings(SCHEMA, given)
    assert field in info.value.errors
