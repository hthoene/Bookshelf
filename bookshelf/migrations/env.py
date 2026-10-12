"""Alembic environment. Migrations run automatically on startup (see ``db.run_migrations``)."""

from alembic import context

from bookshelf import models  # noqa: F401  (registers all tables on Base.metadata)
from bookshelf.config import Settings
from bookshelf.db import Base, make_engine

target_metadata = Base.metadata


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite needs batch mode for most ALTER TABLE operations
    )
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    _run(connection)
else:  # invoked from the alembic CLI
    settings = Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with make_engine(settings.database_url).begin() as cli_connection:
        _run(cli_connection)
