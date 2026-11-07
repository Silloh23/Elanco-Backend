"""Show quarantine behavior for five representative malformed source records."""

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from tickwatch.services.ingestion import ingest


def bad_records() -> list[dict[str, Any]]:
    """Return records that exercise the source cleaner's quarantine reasons."""
    valid_fields = {
        "date": "2024-06-01T12:00:00",
        "location": "Manchester",
        "species": "Marsh tick",
        "latinName": "Ixodes apronophorus",
    }
    return [
        {**valid_fields, "id": "bad-date", "date": "not-a-date"},
        {
            "id": "missing-species",
            "date": valid_fields["date"],
            "location": valid_fields["location"],
            "latinName": valid_fields["latinName"],
        },
        {**valid_fields, "id": "unknown-species", "species": "Uncatalogued pest"},
        {
            **valid_fields,
            "id": "species-latin-mismatch",
            "latinName": "Ixodes canisuga",
        },
        {**valid_fields, "id": "empty-city", "location": ""},
    ]


class _FixtureClient:
    """Yield handcrafted rows through the production ingestion service."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def pages(self) -> list[list[dict[str, Any]]]:
        """Return one source-like page for ingestion."""
        return [self.rows]


def run_demo() -> list[tuple[str, str]]:
    """Ingest bad rows into a temporary DB and return reasons and payloads."""
    with tempfile.TemporaryDirectory(prefix="tickwatch-quarantine-") as directory:
        database_path = str(Path(directory) / "demo.db")
        ingest(_FixtureClient(bad_records()), database_path)  # type: ignore[arg-type]
        connection = sqlite3.connect(database_path)
        result = connection.execute(
            "SELECT reason, raw_payload FROM quarantine ORDER BY id"
        ).fetchall()
        connection.close()
    return [(reason, payload) for reason, payload in result]


def main() -> None:
    """Print quarantine reason codes beside their preserved source payloads."""
    rows = run_demo()
    print("| Reason | Stored raw payload |\n|---|---|")
    for reason, payload in rows:
        safe_payload = json.dumps(json.loads(payload), ensure_ascii=False)
        print(f"| `{reason}` | `{safe_payload}` |")


if __name__ == "__main__":
    main()
