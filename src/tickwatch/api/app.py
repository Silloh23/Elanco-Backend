"""FastAPI application and user-facing query and analytics endpoints."""

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from tickwatch.core.config import Settings
from tickwatch.core.exceptions import NotFound, TickWatchError, UpstreamAPIError
from tickwatch.repositories.database import connect
from tickwatch.repositories.sightings import SightingRepository
from tickwatch.services.analytics import filter_sql
from tickwatch.services.insights import (
    MIN_NON_ZERO_POINTS,
    SIGNIFICANCE_LEVEL,
    anomaly_points,
    chi_square_monthly_test,
    month_of_year_averages,
    non_zero_point_count,
    seasonal_forecast,
)

settings = Settings()


def create_app(database_path: str | None = None) -> FastAPI:
    """Build the API with an explicit database path for dependency-free tests."""
    path = database_path or settings.database_path
    application = FastAPI(title="TickWatch", version="0.1.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def request_context(request: Any, call_next: Any) -> Any:
        """Attach a request identifier and log each request lifecycle."""
        import logging
        import uuid

        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logging.getLogger("tickwatch.api").info(
            "request_complete",
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "status_code": response.status_code,
            },
        )
        return response

    @application.exception_handler(RequestValidationError)
    async def handle_parameter_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        """Map Pydantic request errors into the service error envelope."""
        return JSONResponse(
            status_code=422,
            content={
                "error": {"code": "validation_error", "message": str(error.errors())}
            },
        )

    @application.exception_handler(TickWatchError)
    async def handle_tickwatch_error(
        request: Any, error: TickWatchError
    ) -> JSONResponse:
        """Map expected application exceptions into a stable error shape."""
        code, status = (
            ("not_found", 404)
            if isinstance(error, NotFound)
            else ("upstream_error", 502)
            if isinstance(error, UpstreamAPIError)
            else ("validation_error", 422)
        )
        return JSONResponse(
            status_code=status, content={"error": {"code": code, "message": str(error)}}
        )

    @application.get("/health")
    def health() -> dict[str, str]:
        """Report process health without contacting the source API."""
        return {"status": "ok"}

    @application.get("/sightings")
    def get_sightings(
        start_date: date | None = None,
        end_date: date | None = None,
        region: str | None = None,
        species: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        """Search normalized sightings with filters and stable pagination."""
        if start_date and end_date and start_date > end_date:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "validation_error",
                        "message": "start_date must not exceed end_date",
                    }
                },
            )  # type: ignore[return-value]
        clauses, values = [], []
        base, base_values = filter_sql(
            start_date.isoformat() if start_date else None,
            end_date.isoformat() if end_date else None,
            region,
            species,
        )
        clauses.append(base[7:] if base.startswith(" WHERE ") else "")
        values.extend(base_values)
        where = (
            " WHERE " + " AND ".join(f"({c})" for c in clauses if c)
            if any(clauses)
            else ""
        )
        connection = connect(path)
        repository = SightingRepository(connection)
        rows, total = repository.list_sightings(where, values, limit, offset)
        connection.close()
        return {"items": rows, "total": total, "limit": limit, "offset": offset}

    @application.get("/sightings/{sighting_id}")
    def get_sighting(sighting_id: str) -> dict[str, Any]:
        """Return one sighting or a consistent not-found error."""
        connection = connect(path)
        row = SightingRepository(connection).by_id(sighting_id)
        connection.close()
        if row is None:
            raise NotFound("sighting not found")
        return row

    @application.get("/analytics/by-region")
    def by_region(
        start_date: date | None = None,
        end_date: date | None = None,
        species: str | None = None,
    ) -> dict[str, Any]:
        """Count sightings per region using SQL aggregation."""
        where, values = filter_sql(
            start_date.isoformat() if start_date else None,
            end_date.isoformat() if end_date else None,
            None,
            species,
        )
        connection = connect(path)
        rows = SightingRepository(connection).analytics(
            "SELECT region, COUNT(*) AS count FROM sightings"
            + where
            + " GROUP BY region ORDER BY region",
            values,
        )
        connection.close()
        return {"items": rows}

    @application.get("/analytics/by-species")
    def by_species() -> dict[str, Any]:
        """Return SQL-derived counts and shares for each species."""
        connection = connect(path)
        rows = SightingRepository(connection).analytics(
            "SELECT species, COUNT(*) AS count, ROUND(100.0 * COUNT(*) / NULLIF((SELECT COUNT(*) FROM sightings), 0), 2) AS share_percent FROM sightings GROUP BY species ORDER BY count DESC",
            [],
        )
        connection.close()
        return {"items": rows}

    @application.get("/analytics/trends")
    def trends(
        granularity: str = "weekly",
        region: str | None = None,
        species: str | None = None,
    ) -> dict[str, Any]:
        """Group sightings by calendar week or month and fill date gaps with zero."""
        if granularity not in {"weekly", "monthly"}:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "validation_error",
                        "message": "granularity must be weekly or monthly",
                    }
                },
            )  # type: ignore[return-value]
        clauses, values = [], []
        if region:
            clauses.append("region = ?")
            values.append(region)
        if species:
            clauses.append("species = ?")
            values.append(species)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        bucket = (
            "strftime('%Y-%W-1', observed_at)"
            if granularity == "weekly"
            else "strftime('%Y-%m-01', observed_at)"
        )
        connection = connect(path)
        rows = SightingRepository(connection).analytics(
            f"SELECT {bucket} AS period, COUNT(*) AS count FROM sightings{where} GROUP BY period ORDER BY period",
            values,
        )
        connection.close()
        return {"granularity": granularity, "items": _fill_gaps(rows, granularity)}

    @application.get("/insights/anomalies")
    def anomalies(region: str, granularity: str = "monthly") -> Any:
        """Flag count spikes at monthly resolution, with optional weekly buckets."""
        if granularity not in {"monthly", "weekly"}:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "validation_error",
                        "message": "granularity must be monthly or weekly",
                    }
                },
            )
        bucket = (
            "strftime('%Y-%W-1', observed_at)"
            if granularity == "weekly"
            else "strftime('%Y-%m-01', observed_at)"
        )
        connection = connect(path)
        rows = SightingRepository(connection).analytics(
            f"SELECT {bucket} AS period, COUNT(*) AS count FROM sightings WHERE region = ? GROUP BY period ORDER BY period",
            [region],
        )
        connection.close()
        rows = _fill_gaps(rows, granularity)
        counts = [int(row["count"]) for row in rows]
        response = _insufficient_data_response(counts, granularity)
        if response is not None:
            return response
        points = anomaly_points(counts, settings.anomaly_z_threshold)
        return {
            "region": region,
            "granularity": granularity,
            "items": [
                {
                    "period": rows[int(point["index"])]["period"],
                    **point,
                    "explanation": f"This {granularity[:-2]} is unusually high compared with recent history.",
                }
                for point in points
            ],
        }

    @application.get("/insights/forecast")
    def forecast(region: str, granularity: str = "monthly") -> Any:
        """Project four monthly counts, or weekly counts when requested."""
        if granularity not in {"monthly", "weekly"}:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "validation_error",
                        "message": "granularity must be monthly or weekly",
                    }
                },
            )
        bucket = (
            "strftime('%Y-%W-1', observed_at)"
            if granularity == "weekly"
            else "strftime('%Y-%m-01', observed_at)"
        )
        connection = connect(path)
        rows = SightingRepository(connection).analytics(
            f"SELECT {bucket} AS period, COUNT(*) AS count FROM sightings WHERE region = ? GROUP BY period ORDER BY period",
            [region],
        )
        connection.close()
        rows = _fill_gaps(rows, granularity)
        counts = [int(row["count"]) for row in rows]
        response = _insufficient_data_response(counts, granularity)
        if response is not None:
            return response
        return {
            "region": region,
            "granularity": granularity,
            "method": f"naive: repeat latest four observed {granularity} counts",
            "limitations": "A simple baseline; it ignores external drivers and long-term changes.",
            "forecast": seasonal_forecast(counts),
        }

    @application.get("/insights/seasonality")
    def seasonality(
        city: str | None = None, species: str | None = None
    ) -> dict[str, Any]:
        """Average monthly counts by calendar month with optional filters."""
        clauses, values = [], []
        if city:
            clauses.append("region = ?")
            values.append(city)
        if species:
            clauses.append("species = ?")
            values.append(species)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        connection = connect(path)
        repository = SightingRepository(connection)
        rows = repository.analytics(
            "SELECT strftime('%Y-%m-01', observed_at) AS period, COUNT(*) AS count "
            f"FROM sightings{where} GROUP BY period ORDER BY period",
            values,
        )
        species_test_count = repository.distinct_species_count()
        connection.close()
        monthly_rows = _fill_gaps(rows, "monthly")
        goodness_of_fit = chi_square_monthly_test(monthly_rows)
        if species is not None and goodness_of_fit is not None:
            adjusted_alpha = SIGNIFICANCE_LEVEL / species_test_count
            significant_after_adjustment = (
                float(goodness_of_fit["p_value"]) < adjusted_alpha
            )
            verdict = str(goodness_of_fit["verdict"])
            if (
                bool(goodness_of_fit["significant"])
                and not significant_after_adjustment
            ):
                verdict = (
                    "statistically significant before Bonferroni correction, "
                    "but not after correction at 5%"
                )
            elif significant_after_adjustment:
                verdict = "statistically significant after Bonferroni correction at 5%"
            goodness_of_fit = {
                **goodness_of_fit,
                "adjusted_alpha": adjusted_alpha,
                "significant_after_adjustment": significant_after_adjustment,
                "species_test_count": species_test_count,
                "verdict": verdict,
            }
        return {
            "city": city,
            "species": species,
            "items": month_of_year_averages(monthly_rows),
            "goodness_of_fit": goodness_of_fit,
            "reason": (
                "no_sightings"
                if not monthly_rows
                else "requires_coverage_of_all_calendar_months"
                if goodness_of_fit is None
                else None
            ),
        }

    return application


def _fill_gaps(rows: list[dict[str, Any]], granularity: str) -> list[dict[str, Any]]:
    """Fill missing periods between first and last observed aggregate bucket."""
    if len(rows) < 2:
        return rows
    parsed = [
        datetime.strptime(row["period"], "%Y-%W-%w")
        if granularity == "weekly"
        else datetime.fromisoformat(row["period"])
        for row in rows
    ]
    mapping = {
        period.date().isoformat(): row["count"]
        for period, row in zip(parsed, rows, strict=True)
    }
    result, current, last = [], min(parsed), max(parsed)
    while current <= last:
        key = current.date().isoformat()
        result.append({"period": key, "count": mapping.get(key, 0)})
        if granularity == "weekly":
            current += timedelta(days=7)
        else:
            current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    return result


def _insufficient_data_response(
    counts: list[int], granularity: str
) -> JSONResponse | None:
    """Return an explanatory 422 when a series has too few non-zero periods."""
    non_zero = non_zero_point_count(counts)
    if non_zero >= MIN_NON_ZERO_POINTS:
        return None
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "insufficient_data",
                "message": "This insight requires more periods with sightings.",
                "granularity": granularity,
                "non_zero_points": non_zero,
                "minimum_required": MIN_NON_ZERO_POINTS,
            }
        },
    )


app = create_app()
