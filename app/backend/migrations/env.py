"""Alembic environment. The database URL comes from ``-x url=...`` or the DATABASE_URL setting."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from workflow_demo.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def database_url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("url") or config.get_main_option("sqlalchemy.url")
    if url:
        return url
    import os

    return os.environ.get("DATABASE_URL", "sqlite:///./workflow_demo.db")


def run_migrations() -> None:
    url = database_url()
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            render_as_batch=url.startswith("sqlite"),
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
