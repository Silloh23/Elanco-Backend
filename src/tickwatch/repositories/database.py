"""SQLite connection setup and schema initialization."""

import sqlite3
from pathlib import Path


def connect(database_path: str) -> sqlite3.Connection:
    """Open a row-aware SQLite connection and ensure its schema exists."""
    if database_path != ":memory:":
        Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS sightings (
            id TEXT PRIMARY KEY, observed_at TEXT NOT NULL, region TEXT NOT NULL,
            species TEXT NOT NULL, latin_name TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS quarantine (
            id INTEGER PRIMARY KEY, raw_payload TEXT NOT NULL, reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS ingestion_runs (
            id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT,
            fetched INTEGER NOT NULL DEFAULT 0, inserted INTEGER NOT NULL DEFAULT 0,
            duplicates INTEGER NOT NULL DEFAULT 0, quarantined INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sightings_date ON sightings(observed_at);
        CREATE INDEX IF NOT EXISTS idx_sightings_region ON sightings(region);
        CREATE INDEX IF NOT EXISTS idx_sightings_species ON sightings(species);
        """
    )
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(sightings)")
    }
    if "latin_name" not in columns:
        connection.execute(
            "ALTER TABLE sightings ADD COLUMN latin_name TEXT NOT NULL DEFAULT ''"
        )
    return connection
