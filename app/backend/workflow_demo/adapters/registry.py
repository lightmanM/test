"""Pick the adapter for a platform."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from workflow_demo.adapters.base import AdapterError, PlatformAdapter
from workflow_demo.adapters.fake import FakeAdapter
from workflow_demo.catalog.models import Platform
from workflow_demo.config import Settings


class AdapterRegistry:
    def __init__(self, adapters: dict[Platform, PlatformAdapter]) -> None:
        self._adapters = adapters

    def get(self, platform: Platform) -> PlatformAdapter:
        try:
            return self._adapters[platform]
        except KeyError:
            raise AdapterError(f"Not set up on this server yet ({platform.value} isn't configured)") from None


def fake_registry(popup_url_builder: Callable[[str], str]) -> AdapterRegistry:
    """``popup_url_builder(user_step_state)`` returns the fake Make popup URL."""
    return AdapterRegistry({platform: FakeAdapter(platform, popup_url_builder) for platform in Platform})


def real_registry(settings: Settings, http: httpx.Client) -> AdapterRegistry:
    """Adapters for the platforms whose owner credentials are configured; others are unavailable."""
    from workflow_demo.adapters.modal import SharedBotAdapter
    from workflow_demo.adapters.n8n import N8nAdapter
    from workflow_demo.n8n.client import N8nClient

    # The bot adapter reports its own missing configuration, so it's always registered.
    adapters: dict[Platform, PlatformAdapter] = {Platform.MODAL: SharedBotAdapter(settings)}
    if settings.n8n_base_url and settings.n8n_api_key:
        client = N8nClient(settings.n8n_base_url, settings.n8n_api_key.get_secret_value(), http)
        adapters[Platform.N8N] = N8nAdapter(settings, client, http)
    return AdapterRegistry(adapters)
