"""FastAPI application and user-facing query and analytics endpoints."""

from datetime import date, datetime, timedelta
import math
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

settings = Settings()


def create_app(database_path: str | None = None) -> FastAPI:
    """Build the API with an explicit database path for dependency-free tests."""
    path = database_path or settings.database_path
    application = FastAPI(title="TickWatch", version="0.1.0")
    application.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                              allow_methods=["GET", "POST"], allow_headers=["*"])

    @application.middleware("http")
    async def request_context(request: Any, call_next: Any) -> Any:
        """Attach a request identifier and log each request lifecycle."""
        import logging
        import uuid
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logging.getLogger("tickwatch.api").info("request_complete", extra={"request_id": request_id, "path": request.url.path, "status_code": response.status_code})
        return response

    @application.exception_handler(RequestValidationError)
    async def handle_parameter_error(request: Request, error: RequestValidationError) -> JSONResponse:
        """Map Pydantic request errors into the service error envelope."""
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": str(error.errors())}})

    @application.exception_handler(TickWatchError)
    async def handle_tickwatch_error(request: Any, error: TickWatchError) -> JSONResponse:
        """Map expected application exceptions into a stable error shape."""
        code, status = ("not_found", 404) if isinstance(error, NotFound) else ("upstream_error", 502) if isinstance(error, UpstreamAPIError) else ("validation_error", 422)
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": str(error)}})

    @application.get("/health")
    def health() -> dict[str, str]:
        """Report process health without contacting the source API."""
        return {"status": "ok"}

    @application.get("/sightings")
    def get_sightings(start_date: date | None = None, end_date: date | None = None,
                      region: str | None = None, species: str | None = None,
                      min_lat: float | None = None, max_lat: float | None = None,
                      min_lon: float | None = None, max_lon: float | None = None,
                      lat: float | None = None, lon: float | None = None,
                      radius_km: float | None = Query(default=None, gt=0),
                      limit: int = Query(default=100, ge=1, le=500),
                      offset: int = Query(default=0, ge=0)) -> dict[str, Any]:
        """Search normalized sightings with filters and stable pagination."""
        if start_date and end_date and start_date > end_date:
            return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "start_date must not exceed end_date"}})  # type: ignore[return-value]
        if any(x is not None for x in (min_lat, max_lat, min_lon, max_lon)) and not all(x is not None for x in (min_lat, max_lat, min_lon, max_lon)):
            return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "all bounding box bounds are required"}})  # type: ignore[return-value]
        if (lat is None) != (lon is None) or (radius_km is not None and lat is None):
            return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "lat and lon are required with radius_km"}})  # type: ignore[return-value]
        clauses, values = [], []
        base, base_values = filter_sql(start_date.isoformat() if start_date else None,
                                       end_date.isoformat() if end_date else None, region, species)
        clauses.append(base[7:] if base.startswith(" WHERE ") else "")
        values.extend(base_values)
        if min_lat is not None:
            clauses.extend(["latitude BETWEEN ? AND ?", "longitude BETWEEN ? AND ?"])
            values.extend([min_lat, max_lat, min_lon, max_lon])
        if lat is not None and lon is not None and radius_km is not None:
            clauses.extend(["latitude IS NOT NULL", "longitude IS NOT NULL"])
        where = " WHERE " + " AND ".join(f"({c})" for c in clauses if c) if any(clauses) else ""
        connection = connect(path)
        repository = SightingRepository(connection)
        if lat is not None and lon is not None and radius_km is not None:
            candidates, _ = repository.list_sightings(where, values, 2**31 - 1, 0)
            matches = [row for row in candidates if _distance(lat, lon, row["latitude"], row["longitude"]) <= radius_km]
            total = len(matches)
            rows = matches[offset:offset + limit]
        else:
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
    def by_region(start_date: date | None = None, end_date: date | None = None,
                  species: str | None = None) -> dict[str, Any]:
        """Count sightings per region using SQL aggregation."""
        where, values = filter_sql(start_date.isoformat() if start_date else None,
                                   end_date.isoformat() if end_date else None, None, species)
        connection = connect(path)
        rows = SightingRepository(connection).analytics(
            "SELECT region, COUNT(*) AS count FROM sightings" + where + " GROUP BY region ORDER BY region", values)
        connection.close()
        return {"items": rows}

    @application.get("/analytics/by-species")
    def by_species() -> dict[str, Any]:
        """Return SQL-derived counts and shares for each species."""
        connection = connect(path)
        rows = SightingRepository(connection).analytics(
            "SELECT species, COUNT(*) AS count, ROUND(100.0 * COUNT(*) / NULLIF((SELECT COUNT(*) FROM sightings), 0), 2) AS share_percent FROM sightings GROUP BY species ORDER BY count DESC", [])
        connection.close()
        return {"items": rows}

    @application.get("/analytics/trends")
    def trends(granularity: str = "weekly", region: str | None = None,
               species: str | None = None) -> dict[str, Any]:
        """Group sightings by calendar week or month and fill date gaps with zero."""
        if granularity not in {"weekly", "monthly"}:
            return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "granularity must be weekly or monthly"}})  # type: ignore[return-value]
        clauses, values = [], []
        if region:
            clauses.append("region = ?"); values.append(region)
        if species:
            clauses.append("species = ?"); values.append(species.lower())
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        bucket = "strftime('%Y-%W-1', observed_at)" if granularity == "weekly" else "strftime('%Y-%m-01', observed_at)"
        connection = connect(path)
        rows = SightingRepository(connection).analytics(
            f"SELECT {bucket} AS period, COUNT(*) AS count FROM sightings{where} GROUP BY period ORDER BY period", values)
        connection.close()
        return {"granularity": granularity, "items": _fill_gaps(rows, granularity)}

    @application.get("/insights/anomalies")
    def anomalies(region: str) -> dict[str, Any]:
        """Flag unusually high weekly counts against the region's prior history."""
        from tickwatch.services.insights import anomaly_points
        connection = connect(path)
        rows = SightingRepository(connection).analytics(
            "SELECT strftime('%Y-%W-1', observed_at) AS week, COUNT(*) AS count FROM sightings WHERE region = ? GROUP BY week ORDER BY week", [region])
        connection.close()
        counts = [int(row["count"]) for row in rows]
        points = anomaly_points(counts, settings.anomaly_z_threshold)
        return {"region": region, "items": [{"week": rows[int(point["index"])]["week"], **point,
                "explanation": "This week is unusually high compared with recent history."} for point in points]}

    @application.get("/insights/forecast")
    def forecast(region: str) -> dict[str, Any]:
        """Project four weeks using a seasonal naive baseline."""
        from tickwatch.services.insights import seasonal_forecast
        connection = connect(path)
        rows = SightingRepository(connection).analytics(
            "SELECT strftime('%Y-%W-1', observed_at) AS week, COUNT(*) AS count FROM sightings WHERE region = ? GROUP BY week ORDER BY week", [region])
        connection.close()
        counts = [int(row["count"]) for row in rows]
        return {"region": region, "method": "seasonal naive: repeat latest four observed weeks",
                "limitations": "A simple baseline; it ignores seasonality beyond four weeks and external drivers.",
                "forecast": seasonal_forecast(counts)}

    return application


def _distance(lat: float, lon: float, other_lat: float | None, other_lon: float | None) -> float:
    """Compute great-circle distance in kilometers with the haversine formula."""
    if other_lat is None or other_lon is None:
        return math.inf
    radius = 6371.0
    first, second = math.radians(lat), math.radians(other_lat)
    delta_lat, delta_lon = math.radians(other_lat - lat), math.radians(other_lon - lon)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(first) * math.cos(second) * math.sin(delta_lon / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _fill_gaps(rows: list[dict[str, Any]], granularity: str) -> list[dict[str, Any]]:
    """Fill missing periods between first and last observed aggregate bucket."""
    if len(rows) < 2:
        return rows
    parsed = [datetime.fromisoformat(row["period"]) for row in rows]
    mapping = {row["period"]: row["count"] for row in rows}
    result, current, last = [], min(parsed), max(parsed)
    while current <= last:
        key = current.date().isoformat()
        result.append({"period": key, "count": mapping.get(key, 0)})
        if granularity == "weekly":
            current += timedelta(days=7)
        else:
            current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    return result


app = create_app()
