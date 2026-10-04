"""Filesystem locations shared by the backend and the build scripts."""

import os
from pathlib import Path

REPO_ROOT = Path(os.environ.get("WORKFLOW_DEMO_REPO_ROOT", Path(__file__).resolve().parents[3]))
CATALOG_DIR = Path(os.environ.get("WORKFLOW_DEMO_CATALOG_DIR", REPO_ROOT / "catalog"))
DEMO_PROJECT_DIR = REPO_ROOT / "demo-project"
