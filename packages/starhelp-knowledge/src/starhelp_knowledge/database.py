"""SQLite database lifecycle and numbered schema migrations."""

from __future__ import annotations

import importlib.resources
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from starhelp_knowledge.errors import KnowledgeError

MIGRATION_VERSION = 1


class KnowledgeDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def reader(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def migrate(self) -> int:
        connection = self.connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            row = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
            current = int(row["version"] or 0)
            if current > MIGRATION_VERSION:
                raise KnowledgeError("database schema is newer than this application")
            if current == 0:
                migration = importlib.resources.files("starhelp_knowledge.migrations").joinpath(
                    "001_initial.sql"
                ).read_text(encoding="utf-8")
                connection.executescript(migration)
                from datetime import UTC, datetime

                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (MIGRATION_VERSION, datetime.now(UTC).isoformat()),
                )
            return MIGRATION_VERSION
        finally:
            connection.close()
