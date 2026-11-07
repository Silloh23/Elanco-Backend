"""Validated sighting model and deterministic source-record cleaner."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Any

from tickwatch.core.exceptions import ValidationFailure

UK_BOUNDS = (49.8, 60.9, -8.7, 1.9)


@dataclass(frozen=True)
class Sighting:
    """A normalized tick observation stored by the service."""

    id: str
    observed_at: str
    region: str
    species: str
    latitude: float | None
    longitude: float | None


def _first(raw: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first non-empty value among likely source field aliases."""
    return next((raw[key] for key in keys if raw.get(key) not in (None, "")), None)


def clean_record(raw: dict[str, Any]) -> Sighting:
    """Normalize one source row or raise a reason-coded validation failure."""
    date_value = _first(raw, ("observed_at", "date", "sighting_date", "created_at"))
    region_value = _first(raw, ("region", "location", "county", "area"))
    species_value = _first(raw, ("species", "tick_species", "type"))
    if date_value is None:
        raise ValidationFailure("missing_date")
    if region_value is None:
        raise ValidationFailure("missing_region")
    if species_value is None:
        raise ValidationFailure("missing_species")
    try:
        parsed = datetime.fromisoformat(str(date_value).replace("Z", "+00:00"))
        timestamp = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError as error:
        raise ValidationFailure("invalid_date") from error
    region = re.sub(r"\s+", " ", str(region_value).strip()).title()
    species = re.sub(r"\s+", " ", str(species_value).strip()).lower()
    lat_value = _first(raw, ("latitude", "lat"))
    lon_value = _first(raw, ("longitude", "lon", "lng"))
    latitude = float(lat_value) if lat_value is not None else None
    longitude = float(lon_value) if lon_value is not None else None
    if (latitude is None) != (longitude is None):
        raise ValidationFailure("incomplete_coordinates")
    if latitude is not None and longitude is not None:
        south, north, west, east = UK_BOUNDS
        if not (south <= latitude <= north and west <= longitude <= east):
            raise ValidationFailure("coordinates_outside_uk")
    upstream_id = _first(raw, ("id", "sighting_id"))
    identity = str(upstream_id) if upstream_id is not None else json.dumps(
        [timestamp.isoformat(), region, species, round(latitude, 4) if latitude is not None else None,
         round(longitude, 4) if longitude is not None else None], separators=(",", ":")
    )
    digest = hashlib.sha256(identity.encode()).hexdigest()
    return Sighting(digest, timestamp.isoformat(), region, species, latitude, longitude)


def sighting_dict(sighting: Sighting) -> dict[str, Any]:
    """Convert a normalized sighting to a database-ready mapping."""
    return asdict(sighting)
