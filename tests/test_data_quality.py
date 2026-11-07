"""Tests for source normalization, quarantine, and data profiling rules."""

import logging

import pytest

from scripts.demo_quarantine import bad_records
from scripts.profile_data import profile
from tickwatch.core.exceptions import ValidationFailure
from tickwatch.models.sighting import clean_record
from tickwatch.services.ingestion import ingest


def _record(
    record_id: str,
    date: str = "2024-01-01T12:00:00",
    location: str = "Manchester",
    species: str = "Marsh tick",
    latin_name: str = "Ixodes apronophorus",
) -> dict[str, str]:
    """Build a realistic source object for focused quality checks."""
    return {
        "id": record_id,
        "date": date,
        "location": location,
        "species": species,
        "latinName": latin_name,
    }


def test_known_categories_normalize_case_and_whitespace() -> None:
    sighting = clean_record(
        _record(
            "case-test",
            location="  manchester  ",
            species=" MARSH   TICK ",
            latin_name="IXODES   APRONOPHORUS",
        )
    )
    assert sighting.region == "Manchester"
    assert sighting.species == "Marsh tick"
    assert sighting.latin_name == "Ixodes apronophorus"


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        (_record("typo", location="Manchesterr"), "possible_location_spelling_variant"),
        (
            _record("mismatch", latin_name="Ixodes canisuga"),
            "species_latin_name_mismatch",
        ),
        (_record("unknown", species="Uncatalogued pest"), "unknown_species"),
    ],
)
def test_likely_spelling_and_taxonomy_mismatch_are_rejected(
    record: dict[str, str], reason: str
) -> None:
    with pytest.raises(ValidationFailure, match=reason):
        clean_record(record)


def test_profile_finds_variants_duplicates_dates_and_pair_mismatches() -> None:
    rows = [
        _record("1"),
        _record(
            "2",
            date="2024-01-01",
            location="manchester",
            species="marsh   tick",
        ),
        _record("3"),
        _record("4", location="Manchesterr", latin_name="Ixodes canisuga"),
    ]
    result = profile(rows)
    assert result["date_format_counts"] == {
        "ISO date": 1,
        "ISO datetime without timezone": 3,
    }
    assert result["duplicate_content_rows"] == 1
    assert result["species_latin_mismatch_rows"] == 1
    assert result["issue_counts"]["date_format_variant_rows"] == 1
    assert result["issue_counts"]["case_or_whitespace_variant_rows"] > 0
    assert result["issue_counts"]["spelling_variant_rows"] > 0


def test_ingest_quarantines_bad_categories_and_flags_content_duplicates(
    tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    class FixtureClient:
        def pages(self):
            yield [
                _record("one"),
                _record("two"),
                _record("typo", location="Manchesterr"),
                _record("mismatch", latin_name="Ixodes canisuga"),
            ]

    caplog.set_level(logging.WARNING, logger="tickwatch.services.ingestion")
    summary = ingest(FixtureClient(), str(tmp_path / "quality.db"))
    assert summary == {
        "fetched": 4,
        "inserted": 2,
        "duplicates": 0,
        "quarantined": 2,
    }
    assert "duplicate_content_tuple" in caplog.text


def test_quarantine_demo_records_keep_raw_payloads_and_reason_codes(tmp_path) -> None:
    import json
    import sqlite3

    records = bad_records()

    class FixtureClient:
        def pages(self):
            yield records

    database_path = str(tmp_path / "quarantine-demo.db")
    summary = ingest(FixtureClient(), database_path)
    connection = sqlite3.connect(database_path)
    rows = connection.execute("SELECT reason, raw_payload FROM quarantine").fetchall()
    connection.close()
    reason_by_id = {json.loads(payload)["id"]: reason for reason, payload in rows}
    assert summary["quarantined"] == 5
    assert reason_by_id == {
        "bad-date": "invalid_date",
        "missing-species": "missing_species",
        "unknown-species": "unknown_species",
        "species-latin-mismatch": "species_latin_name_mismatch",
        "empty-city": "missing_region",
    }
