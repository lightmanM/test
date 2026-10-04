"""Everything a request or job needs, built once per app."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx

from workflow_demo.adapters.registry import AdapterRegistry
from workflow_demo.catalog.models import Catalog
from workflow_demo.config import Settings
from workflow_demo.crypto import SecretBox
from workflow_demo.db import Database
from workflow_demo.nango import NangoClient
from workflow_demo.security import Signer

if TYPE_CHECKING:
    from workflow_demo.services.jobs import JobRunner


@dataclass
class AppServices:
    settings: Settings
    db: Database
    catalog: Catalog
    registry: AdapterRegistry
    signer: Signer
    nango: NangoClient | None = None
    secret_box: SecretBox | None = None
    http: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=20))
    runner: JobRunner = field(init=False)
