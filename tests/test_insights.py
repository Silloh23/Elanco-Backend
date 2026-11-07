"""Synthetic coverage for sparse-series guards and month-of-year averages."""

from fastapi.testclient import TestClient

from tickwatch.api.app import create_app
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
