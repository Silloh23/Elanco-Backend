"""Typed SQL repository for sightings, quarantine and run accounting."""

import json
import sqlite3
from typing import Any

from tickwatch.models.sighting import Sighting


class SightingRepository:
    """Encapsulate parameterized queries for SQLite persistence."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Bind this repository to one transaction-scoped connection."""
        self.connection = connection

    def insert_batch(self, batch: list[Sighting]) -> tuple[int, int]:
        """Insert a batch idempotently and return inserted and duplicate counts."""
        before = self.connection.total_changes
        self.connection.executemany(
            """INSERT OR IGNORE INTO sightings
               (id, observed_at, region, species, latin_name)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    x.id,
                    x.observed_at,
                    x.region,
                    x.species,
                    x.latin_name,
                )
                for x in batch
            ],
        )
        inserted = self.connection.total_changes - before
        self.connection.commit()
        return inserted, len(batch) - inserted

    def quarantine(self, raw: dict[str, Any], reason: str) -> None:
        """Persist raw rejected data and its stable reason code."""
        self.connection.execute(
            "INSERT INTO quarantine(raw_payload, reason) VALUES (?, ?)",
            (json.dumps(raw, default=str), reason),
        )
        self.connection.commit()

    def list_sightings(
        self, where: str, values: list[Any], limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one stable page and total for a validated filter expression."""
        total = self.connection.execute(
            f"SELECT COUNT(*) FROM sightings {where}", values
        ).fetchone()[0]
        rows = self.connection.execute(
            f"""SELECT id, observed_at, region, species, latin_name FROM sightings
                {where} ORDER BY observed_at, id LIMIT ? OFFSET ?""",
            [*values, limit, offset],
        ).fetchall()
        return [dict(row) for row in rows], int(total)

    def analytics(self, sql: str, values: list[Any]) -> list[dict[str, Any]]:
        """Run a fixed repository-owned aggregate query."""
        return [dict(row) for row in self.connection.execute(sql, values).fetchall()]

    def reconciliation_aggregates(self) -> dict[str, Any]:
        """Return local totals grouped by city and species for source comparison."""
        total = self.connection.execute("SELECT COUNT(*) FROM sightings").fetchone()[0]
        cities = self.analytics(
            "SELECT region, COUNT(*) AS count FROM sightings GROUP BY region", []
        )
        species = self.analytics(
            "SELECT species, COUNT(*) AS count FROM sightings GROUP BY species", []
        )
        return {
            "total": int(total),
            "cities": {row["region"]: int(row["count"]) for row in cities},
            "species": {row["species"]: int(row["count"]) for row in species},
        }

    def by_id(self, sighting_id: str) -> dict[str, Any] | None:
        """Look up one sighting by its stable identifier."""
        row = self.connection.execute(
            """SELECT id, observed_at, region, species, latin_name
               FROM sightings WHERE id = ?""",
            (sighting_id,),
        ).fetchone()
        return dict(row) if row else None

    def distinct_species_count(self) -> int:
        """Return the number of observed species for multiple-test correction."""
        row = self.connection.execute(
            "SELECT COUNT(DISTINCT species) FROM sightings"
        ).fetchone()
        return int(row[0])
