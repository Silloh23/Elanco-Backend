"""Ingestion orchestration and run summaries."""

import json
import logging
from datetime import UTC, datetime

from tickwatch.clients.source import SourceClient
from tickwatch.core.exceptions import UpstreamAPIError, ValidationFailure
from tickwatch.models.sighting import clean_record
from tickwatch.repositories.database import connect
from tickwatch.repositories.sightings import SightingRepository

logger = logging.getLogger(__name__)
BATCH_SIZE = 250


def ingest(client: SourceClient, database_path: str) -> dict[str, int]:
    """Fetch, validate, quarantine, deduplicate and account for one source run."""
    connection = connect(database_path)
    repository = SightingRepository(connection)
    started = datetime.now(UTC).isoformat()
    cursor = connection.execute(
        "INSERT INTO ingestion_runs(started_at, status) VALUES (?, 'running')",
        (started,),
    )
    run_id = cursor.lastrowid
    assert run_id is not None
    totals: dict[str, int] = {
        "fetched": 0,
        "inserted": 0,
        "duplicates": 0,
        "quarantined": 0,
    }
    batch = []
    content_keys: set[tuple[str, str, str]] = set()
    try:
        for page in client.pages():
            for raw in page:
                totals["fetched"] += 1
                try:
                    sighting = clean_record(raw)
                    content_key = (
                        sighting.observed_at,
                        sighting.region,
                        sighting.species,
                    )
                    if content_key in content_keys:
                        logger.warning(
                            "duplicate_content_tuple",
                            extra={"sighting_id": sighting.id},
                        )
                    content_keys.add(content_key)
                    batch.append(sighting)
                except (ValidationFailure, TypeError, ValueError) as error:
                    repository.quarantine(raw, str(error))
                    totals["quarantined"] += 1
                if len(batch) >= BATCH_SIZE:
                    inserted, duplicates = repository.insert_batch(batch)
                    totals["inserted"] += inserted
                    totals["duplicates"] += duplicates
                    batch.clear()
            # Commit each completed page so an upstream failure on a later page
            # does not discard sightings already fetched and validated.
            if batch:
                inserted, duplicates = repository.insert_batch(batch)
                totals["inserted"] += inserted
                totals["duplicates"] += duplicates
                batch.clear()
        if batch:
            inserted, duplicates = repository.insert_batch(batch)
            totals["inserted"] += inserted
            totals["duplicates"] += duplicates
        connection.execute(
            "UPDATE ingestion_runs SET ended_at=?, fetched=?, inserted=?, duplicates=?, quarantined=?, status='success' WHERE id=?",
            (datetime.now(UTC).isoformat(), *totals.values(), run_id),
        )
        connection.commit()
        return totals
    except UpstreamAPIError:
        connection.rollback()
        connection.execute(
            "UPDATE ingestion_runs SET ended_at=?, fetched=?, inserted=?, duplicates=?, quarantined=?, status='failed' WHERE id=?",
            (datetime.now(UTC).isoformat(), *totals.values(), run_id),
        )
        connection.commit()
        logger.exception("Ingestion failed", extra={"run_id": run_id})
        raise
    finally:
        connection.close()


def serialize_raw(raw: dict[str, object]) -> str:
    """Serialize an input mapping for diagnostics."""
    return json.dumps(raw, default=str)
