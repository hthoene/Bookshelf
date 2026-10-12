"""Database engine setup and schema migrations (SQLite + Alembic)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Naive UTC timestamp. SQLite has no timezone support, so all datetimes are stored as UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


def _casefold(value: str | None) -> str | None:
    return value.casefold() if value is not None else None


def make_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
        # Unicode-aware case folding for search and sorting (SQLite's LOWER() is ASCII-only).
        dbapi_connection.create_function("casefold", 1, _casefold, deterministic=True)

    return engine


def run_migrations(engine: Engine) -> None:
    """Upgrade the database schema to the latest Alembic revision."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def init_database(url: str) -> sessionmaker[Session]:
    engine = make_engine(url)
    run_migrations(engine)
    return sessionmaker(engine, expire_on_commit=False)
