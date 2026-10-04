"""Alembic environment. The database URL comes from ``-x url=...`` or the DATABASE_URL setting."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from workflow_demo.config import DatabaseSettings
from workflow_demo.db import Base, normalize_database_url

config = context.config
if config.config_file_name is not None:
    # Keep the app's loggers working when migrations run in-process (tests, startup scripts).
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def database_url() -> str:
    """``-x url=...``, then ``sqlalchemy.url``, then DATABASE_URL from the env or app/backend/.env."""
    url = context.get_x_argument(as_dictionary=True).get("url") or config.get_main_option("sqlalchemy.url")
    return normalize_database_url(url or DatabaseSettings().database_url)


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
