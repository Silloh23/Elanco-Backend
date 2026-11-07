"""Synthetic coverage for sparse-series guards and month-of-year averages."""

from fastapi.testclient import TestClient

from tickwatch.api.app import create_app
from tickwatch.models.sighting import SPECIES_TO_LATIN_NAME
from tickwatch.services.ingestion import ingest
from tickwatch.services.insights import chi_square_monthly_test


def _sighting(
    record_id: str,
    date: str,
    city: str = "Manchester",
    species: str = "Marsh tick",
    latin_name: str = "Ixodes apronophorus",
) -> dict[str, str]:
    """Build one source-format record for the temporary insights database."""
    return {
        "id": record_id,
        "date": date,
        "location": city,
        "species": species,
        "latinName": latin_name,
    }


def _client_with_rows(tmp_path, rows: list[dict[str, str]]) -> TestClient:
    database_path = str(tmp_path / "insights.db")

    class FixtureClient:
        def pages(self):
            yield rows

    ingest(FixtureClient(), database_path)
    return TestClient(create_app(database_path))


def test_monthly_chi_square_distinguishes_flat_and_seasonal_series() -> None:
    flat = [{"period": f"2024-{month:02d}-01", "count": 100} for month in range(1, 13)]
    seasonal = [
        {"period": f"2024-{month:02d}-01", "count": 500 if month == 7 else 1}
        for month in range(1, 13)
    ]
    flat_result = chi_square_monthly_test(flat)
    seasonal_result = chi_square_monthly_test(seasonal)
    assert flat_result is not None
    assert flat_result["degrees_of_freedom"] == 11
    assert flat_result["p_value"] > 0.05
    assert flat_result["verdict"] == "no statistically significant seasonality at 5%"
    assert seasonal_result is not None
    assert seasonal_result["p_value"] < 0.05
    assert seasonal_result["verdict"] == "statistically significant seasonality at 5%"


def test_species_seasonality_applies_bonferroni_correction(tmp_path) -> None:
    records = []
    for month in range(1, 13):
        target_count = 150 if month == 7 else 100
        for index in range(target_count):
            records.append(
                _sighting(
                    f"marsh-{month}-{index}",
                    f"2024-{month:02d}-{index // 24 + 1:02d}T{index % 24:02d}:00:00",
                )
            )
        for species, latin_name in SPECIES_TO_LATIN_NAME.items():
            if species == "Marsh tick":
                continue
            records.append(
                _sighting(
                    f"{species}-{month}",
                    f"2024-{month:02d}-01T12:00:00",
                    species=species,
                    latin_name=latin_name,
                )
            )
    client = _client_with_rows(tmp_path, records)
    response = client.get("/insights/seasonality", params={"species": "Marsh tick"})
    assert response.status_code == 200
    result = response.json()["goodness_of_fit"]
    assert result["p_value"] < 0.05
    assert result["adjusted_alpha"] == 0.01
    assert result["species_test_count"] == 5
    assert not result["significant_after_adjustment"]
    assert "significant before Bonferroni correction" in result["verdict"]
    assert "but not after correction" in result["verdict"]


def test_monthly_anomaly_and_forecast_return_clear_sparse_data_guard(
    tmp_path,
) -> None:
    client = _client_with_rows(
        tmp_path,
        [
            _sighting("jan", "2022-01-10T12:00:00"),
            _sighting("may", "2023-05-10T12:00:00"),
            _sighting("oct", "2024-10-10T12:00:00"),
        ],
    )
    anomaly = client.get("/insights/anomalies", params={"region": "Manchester"})
    forecast = client.get("/insights/forecast", params={"region": "Manchester"})
    weekly_forecast = client.get(
        "/insights/forecast",
        params={"region": "Manchester", "granularity": "weekly"},
    )
    assert anomaly.status_code == 422
    assert anomaly.json()["error"]["code"] == "insufficient_data"
    assert anomaly.json()["error"]["granularity"] == "monthly"
    assert anomaly.json()["error"]["non_zero_points"] == 3
    assert anomaly.json()["error"]["minimum_required"] == 9
    assert forecast.status_code == 422
    assert forecast.json()["error"]["granularity"] == "monthly"
    assert weekly_forecast.status_code == 422
    assert weekly_forecast.json()["error"]["granularity"] == "weekly"


def test_seasonality_averages_zero_months_and_applies_optional_filters(
    tmp_path,
) -> None:
    client = _client_with_rows(
        tmp_path,
        [
            _sighting("jan-23-a", "2023-01-10T12:00:00"),
            _sighting("jan-23-b", "2023-01-11T12:00:00"),
            _sighting("jan-24-a", "2024-01-10T12:00:00"),
            _sighting("jan-24-b", "2024-01-11T12:00:00"),
            _sighting("jan-24-c", "2024-01-12T12:00:00"),
            _sighting("jan-24-d", "2024-01-13T12:00:00"),
            _sighting("dec-24", "2024-12-10T12:00:00"),
            _sighting(
                "london-jan",
                "2024-01-15T12:00:00",
                city="London",
                species="Fox/badger tick",
                latin_name="Ixodes canisuga",
            ),
        ],
    )
    response = client.get(
        "/insights/seasonality",
        params={"city": "Manchester", "species": "Marsh tick"},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 12
    assert items[0] == {
        "month": 1,
        "month_name": "January",
        "average_count": 3.0,
        "years": 2,
    }
    assert items[1]["average_count"] == 0.0
    assert items[11]["average_count"] == 0.5
    assert response.json()["goodness_of_fit"]["degrees_of_freedom"] == 11
    assert response.json()["goodness_of_fit"]["p_value"] < 0.05

    city_only = client.get("/insights/seasonality", params={"city": "London"})
    assert city_only.status_code == 200
    assert city_only.json()["items"][0]["average_count"] == 1.0
    assert city_only.json()["goodness_of_fit"] is None
    assert city_only.json()["reason"] == "requires_coverage_of_all_calendar_months"


def test_aggregate_endpoints_match_independent_raw_sql(tmp_path) -> None:
    import sqlite3

    rows = [
        _sighting("manchester-jan23-a", "2023-01-10T12:00:00"),
        _sighting("manchester-jan23-b", "2023-01-11T12:00:00"),
        _sighting("manchester-jan24-a", "2024-01-10T12:00:00"),
        _sighting("manchester-jan24-b", "2024-01-11T12:00:00"),
        _sighting("manchester-jan24-c", "2024-01-12T12:00:00"),
        _sighting("manchester-jan24-d", "2024-01-13T12:00:00"),
        _sighting("manchester-dec24", "2024-12-10T12:00:00"),
        _sighting(
            "london-jan24",
            "2024-01-15T12:00:00",
            city="London",
            species="Fox/badger tick",
            latin_name="Ixodes canisuga",
        ),
    ]
    client = _client_with_rows(tmp_path, rows)
    database_path = str(tmp_path / "insights.db")
    connection = sqlite3.connect(database_path)

    raw_regions = dict(
        connection.execute(
            "SELECT region, COUNT(*) FROM sightings GROUP BY region ORDER BY region"
        ).fetchall()
    )
    api_regions = client.get("/analytics/by-region").json()["items"]
    assert {row["region"]: row["count"] for row in api_regions} == raw_regions

    raw_species = dict(
        connection.execute(
            "SELECT species, COUNT(*) FROM sightings GROUP BY species"
        ).fetchall()
    )
    total = connection.execute("SELECT COUNT(*) FROM sightings").fetchone()[0]
    api_species = client.get("/analytics/by-species").json()["items"]
    assert {row["species"]: row["count"] for row in api_species} == raw_species
    assert {row["species"]: row["share_percent"] for row in api_species} == {
        name: round(100 * count / total, 2) for name, count in raw_species.items()
    }

    raw_trends = dict(
        connection.execute(
            """SELECT strftime('%Y-%m-01', observed_at), COUNT(*) FROM sightings
               GROUP BY 1 ORDER BY 1"""
        ).fetchall()
    )
    connection.close()
    api_trends = client.get(
        "/analytics/trends", params={"granularity": "monthly"}
    ).json()["items"]
    assert {row["period"]: row["count"] for row in api_trends} == raw_trends | {
        "2023-02-01": 0,
        "2023-03-01": 0,
        "2023-04-01": 0,
        "2023-05-01": 0,
        "2023-06-01": 0,
        "2023-07-01": 0,
        "2023-08-01": 0,
        "2023-09-01": 0,
        "2023-10-01": 0,
        "2023-11-01": 0,
        "2023-12-01": 0,
        "2024-02-01": 0,
        "2024-03-01": 0,
        "2024-04-01": 0,
        "2024-05-01": 0,
        "2024-06-01": 0,
        "2024-07-01": 0,
        "2024-08-01": 0,
        "2024-09-01": 0,
        "2024-10-01": 0,
        "2024-11-01": 0,
    }

    raw_month_totals = dict(
        sqlite3.connect(database_path)
        .execute(
            "SELECT CAST(strftime('%m', observed_at) AS INTEGER), COUNT(*) "
            "FROM sightings GROUP BY 1"
        )
        .fetchall()
    )
    api_seasonality = client.get("/insights/seasonality").json()["items"]
    assert {row["month"]: row["average_count"] for row in api_seasonality} == {
        month: round(raw_month_totals.get(month, 0) / 2, 2) for month in range(1, 13)
    }
