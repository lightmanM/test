"""Pick the adapter for a platform."""

from __future__ import annotations

from collections.abc import Callable

from workflow_demo.adapters.base import AdapterError, PlatformAdapter
from workflow_demo.adapters.fake import FakeAdapter
from workflow_demo.catalog.models import Platform


class AdapterRegistry:
    def __init__(self, adapters: dict[Platform, PlatformAdapter]) -> None:
        self._adapters = adapters

    def get(self, platform: Platform) -> PlatformAdapter:
        try:
            return self._adapters[platform]
        except KeyError:
            raise AdapterError(f"{platform.value} deployments are not configured") from None


def fake_registry(popup_url_builder: Callable[[str], str]) -> AdapterRegistry:
    """``popup_url_builder(user_step_state)`` returns the fake Make popup URL."""
    return AdapterRegistry({platform: FakeAdapter(platform, popup_url_builder) for platform in Platform})
