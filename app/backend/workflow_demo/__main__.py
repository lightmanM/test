"""Local development server: ``python -m workflow_demo`` (reads app/backend/.env).

Creates the SQLite tables directly; deployed databases use ``alembic upgrade head``.
"""

from __future__ import annotations

import logging

import uvicorn

from workflow_demo.app import build_services, create_app
from workflow_demo.config import get_settings


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    svc = build_services(settings)
    if settings.database_url.startswith("sqlite"):
        svc.db.create_all()
    uvicorn.run(create_app(settings, svc), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
