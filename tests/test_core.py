"""Fast unit coverage for cleaning and pure insight calculations."""

import pytest

from tickwatch.core.exceptions import ValidationFailure
from tickwatch.models.sighting import clean_record
from tickwatch.services.insights import anomaly_points, seasonal_forecast


def test_clean_record_normalizes_and_deduplicates() -> None:
    """Equivalent normalized reports share a deterministic identifier."""
    first = clean_record(
        {
            "date": "2026-01-01",
            "id": "fixture-one",
            "latinName": "Ixodes apronophorus",
            "location": "  manchester  ",
            "species": " Marsh   tick ",
        }
    )
    second = clean_record(
        {
            "observed_at": "2026-01-01T00:00:00Z",
            "id": "fixture-one",
            "latinName": "Ixodes apronophorus",
            "location": "Manchester",
            "species": "Marsh tick",
        }
    )
    assert first == second


def test_clean_record_quarantinable_rejection() -> None:
    """Missing required fields yield stable reason codes."""
    with pytest.raises(ValidationFailure, match="missing_date"):
        clean_record({"region": "Kent", "species": "tick"})


def test_source_location_without_coordinates_is_valid() -> None:
    """The source provides city names but no latitude or longitude."""
    record = clean_record(
        {
            "id": "source-id",
            "date": "2026-01-01T00:00:00",
            "latinName": "Ixodes apronophorus",
            "location": "Manchester",
            "species": "Marsh tick",
        }
    )
    assert record.id == "source-id"
    assert record.region == "Manchester"
    assert record.latin_name == "Ixodes apronophorus"


def test_anomaly_and_forecast_baselines() -> None:
    """Known spikes are flagged, flat series stay quiet, and forecast repeats."""
    assert anomaly_points([4] * 8 + [40])
    assert anomaly_points([4] * 9) == []
    assert seasonal_forecast([1, 2]) == [1.0, 2.0, 1.0, 2.0]


def test_source_client_list_response_and_retries() -> None:
    """Client retries a transient error and yields the source's list response."""
    import httpx

    from tickwatch.clients.source import SourceClient

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        assert not request.url.params
        records = [
            {
                "id": "fixture-one",
                "date": "2026-01-01T00:00:00",
                "latinName": "Ixodes apronophorus",
                "location": "Manchester",
                "species": "Marsh tick",
            }
        ]
        return httpx.Response(200, json=records)

    client = SourceClient(
        "https://unit.test/data", attempts=2, transport=httpx.MockTransport(handler)
    )
    try:
        assert len(list(client.pages())) == 1
        assert calls == 2
    finally:
        client.close()


def test_ingest_idempotency_and_quarantine(tmp_path) -> None:
    """Repeated source rows stay unique and malformed rows remain preserved."""
    import sqlite3

    from tickwatch.services.ingestion import ingest

    valid = {
        "id": "fixture-one",
        "date": "2026-01-01",
        "latinName": "Ixodes apronophorus",
        "location": "Manchester",
        "species": "Marsh tick",
    }

    class FixtureClient:
        def pages(self):
            yield [valid, valid, {"species": "tick"}]

    database_path = str(tmp_path / "ticks.db")
    first = ingest(FixtureClient(), database_path)
    second = ingest(FixtureClient(), database_path)
    assert first == {"fetched": 3, "inserted": 1, "duplicates": 1, "quarantined": 1}
    assert second == {"fetched": 3, "inserted": 0, "duplicates": 2, "quarantined": 1}
    connection = sqlite3.connect(database_path)
    assert connection.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0] == 2
    connection.close()


def test_failed_ingestion_marks_run_failed(tmp_path) -> None:
    """An upstream interruption preserves committed data and records failure."""
    import sqlite3

    from tickwatch.core.exceptions import UpstreamAPIError
    from tickwatch.services.ingestion import ingest

    class BrokenClient:
        def pages(self):
            yield [
                {
                    "id": "fixture-one",
                    "date": "2026-01-01",
                    "latinName": "Ixodes apronophorus",
                    "location": "Manchester",
                    "species": "Marsh tick",
                }
            ]
            raise UpstreamAPIError("offline")

    database_path = str(tmp_path / "ticks.db")
    with pytest.raises(UpstreamAPIError):
        ingest(BrokenClient(), database_path)
    connection = sqlite3.connect(database_path)
    assert connection.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 1
    assert (
        connection.execute("SELECT status FROM ingestion_runs").fetchone()[0]
        == "failed"
    )
    connection.close()
