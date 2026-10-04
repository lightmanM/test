"""Filesystem locations shared by the backend and the build scripts.

Defaults assume a source checkout (``pip install -e app/backend``). A deployed image that installs
the package normally must set ``WORKFLOW_DEMO_CATALOG_DIR`` (and ``WORKFLOW_DEMO_REPO_ROOT`` if it
also ships ``demo-project/``).
"""

import os
from pathlib import Path

REPO_ROOT = Path(os.environ.get("WORKFLOW_DEMO_REPO_ROOT", Path(__file__).resolve().parents[3]))
CATALOG_DIR = Path(os.environ.get("WORKFLOW_DEMO_CATALOG_DIR", REPO_ROOT / "catalog"))
DEMO_PROJECT_DIR = REPO_ROOT / "demo-project"
FRONTEND_DIST = Path(os.environ.get("WORKFLOW_DEMO_FRONTEND_DIST", REPO_ROOT / "app" / "frontend" / "dist"))
