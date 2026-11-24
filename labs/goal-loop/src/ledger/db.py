# Copyright (c) 2026 Zenable, Inc.
"""SQLite connection and schema management."""

import sqlite3
from pathlib import Path

from ledger.config import settings

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "schema.sql"


def connect(path: Path | str) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA journal_mode={settings.journal_mode}")
    return connection


def apply_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_FILE.read_text())


def reset(connection: sqlite3.Connection) -> None:
    """Drop everything and apply the schema again."""
    connection.executescript("DROP TABLE IF EXISTS order_items; DROP TABLE IF EXISTS orders;")
    apply_schema(connection)
