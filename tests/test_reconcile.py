"""Mocked source checks for the reconciliation command."""

from urllib.parse import unquote

import httpx

from scripts.reconcile_upstream import reconcile
from tickwatch.services.ingestion import ingest


def _row(
    record_id: str, location: str, species: str, latin_name: str
) -> dict[str, str]:
    return {
        "id": record_id,
        "date": "2024-01-01T12:00:00",
        "location": location,
        "species": species,
        "latinName": latin_name,
    }


def test_reconcile_reports_city_and_species_differences(tmp_path) -> None:
    local_rows = [
        _row("local-1", "London", "Marsh tick", "Ixodes apronophorus"),
        _row("local-2", "Manchester", "Fox/badger tick", "Ixodes canisuga"),
    ]

    class LocalClient:
        def pages(self):
            yield local_rows

    database_path = str(tmp_path / "reconcile.db")
    ingest(LocalClient(), database_path)
    upstream_rows = [
        _row("source-1", "London", "Marsh tick", "Ixodes apronophorus"),
        _row("source-2", "Bristol", "Tree-hole tick", "Ixodes arboricola"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        if path == "/data/stats":
            return httpx.Response(200, json={"total_sightings": 2})
        if path == "/data/tick-sightings":
            return httpx.Response(200, json=upstream_rows)
        if "/city/" in path:
            city = path.rsplit("/", 1)[-1]
            return httpx.Response(
                200, json=[row for row in upstream_rows if row["location"] == city]
            )
        if "/species/" in path:
            species = path.rsplit("/", 1)[-1]
            return httpx.Response(
                200, json=[row for row in upstream_rows if row["species"] == species]
            )
        return httpx.Response(404, json={"error": "Not found"})

    result = reconcile(
        database_path,
        "https://unit.test/data/tick-sightings",
        httpx.MockTransport(handler),
    )
    diffs = {
        (row["dimension"], row["value"], row["difference"])
        for row in result["differences"]
    }
    assert ("city", "Manchester", 1) in diffs
    assert ("city", "Bristol", -1) in diffs
    assert ("species", "Fox/badger tick", 1) in diffs
    assert ("species", "Tree-hole tick", -1) in diffs
    assert not any(row["dimension"] == "total" for row in result["differences"])
