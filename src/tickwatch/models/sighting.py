"""Validated sighting model and deterministic source-record cleaner."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

from tickwatch.core.exceptions import ValidationFailure

SPECIES_TO_LATIN_NAME = {
    "Fox/badger tick": "Ixodes canisuga",
    "Marsh tick": "Ixodes apronophorus",
    "Passerine tick": "Dermacentor frontalis",
    "Southern rodent tick": "Ixodes acuminatus",
    "Tree-hole tick": "Ixodes arboricola",
}
SOURCE_LOCATIONS = {
    "Birmingham",
    "Bristol",
    "Cardiff",
    "Edinburgh",
    "Glasgow",
    "Leeds",
    "Leicester",
    "Liverpool",
    "London",
    "Manchester",
    "Newcastle",
    "Nottingham",
    "Sheffield",
    "Southampton",
}


@dataclass(frozen=True)
class Sighting:
    """A normalized tick observation stored by the service."""

    id: str
    observed_at: str
    region: str
    species: str
    latin_name: str


def _first(raw: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first non-empty value among likely source field aliases."""
    return next((raw[key] for key in keys if raw.get(key) not in (None, "")), None)


def _category_value(value: Any, canonical_values: set[str], field: str) -> str:
    """Normalize case and whitespace, quarantining likely spelling variants."""
    normalized = re.sub(r"\s+", " ", str(value).strip())
    by_casefold = {item.casefold(): item for item in canonical_values}
    canonical = by_casefold.get(normalized.casefold())
    if canonical is not None:
        return canonical
    folded = normalized.casefold()
    if any(
        min(len(folded), len(item)) >= 5
        and SequenceMatcher(None, folded, item.casefold()).ratio() >= 0.9
        for item in canonical_values
    ):
        raise ValidationFailure(f"possible_{field}_spelling_variant")
    return normalized.title() if field == "location" else normalized


def clean_record(raw: dict[str, Any]) -> Sighting:
    """Normalize one source row or raise a reason-coded validation failure."""
    date_value = _first(raw, ("observed_at", "date", "sighting_date", "created_at"))
    region_value = _first(raw, ("region", "location", "county", "area"))
    species_value = _first(raw, ("species", "tick_species", "type"))
    latin_name_value = _first(raw, ("latinName", "latin_name", "scientific_name"))
    if date_value is None:
        raise ValidationFailure("missing_date")
    if region_value is None:
        raise ValidationFailure("missing_region")
    if species_value is None:
        raise ValidationFailure("missing_species")
    if latin_name_value is None:
        raise ValidationFailure("missing_latin_name")
    try:
        parsed = datetime.fromisoformat(str(date_value))
        timestamp = (
            parsed.replace(tzinfo=UTC)
            if parsed.tzinfo is None
            else parsed.astimezone(UTC)
        )
    except ValueError as error:
        raise ValidationFailure("invalid_date") from error
    region = _category_value(region_value, SOURCE_LOCATIONS, "location")
    species = _category_value(species_value, set(SPECIES_TO_LATIN_NAME), "species")
    latin_name = _category_value(
        latin_name_value, set(SPECIES_TO_LATIN_NAME.values()), "latin_name"
    )
    expected_latin_name = SPECIES_TO_LATIN_NAME.get(species)
    if expected_latin_name is not None and expected_latin_name != latin_name:
        raise ValidationFailure("species_latin_name_mismatch")
    upstream_id = _first(raw, ("id", "sighting_id"))
    identity = (
        str(upstream_id)
        if upstream_id is not None
        else json.dumps(
            [
                timestamp.isoformat(),
                region,
                species,
                latin_name,
            ],
            separators=(",", ":"),
        )
    )
    sighting_id = (
        str(upstream_id)
        if upstream_id is not None
        else hashlib.sha256(identity.encode()).hexdigest()
    )
    return Sighting(
        sighting_id,
        timestamp.isoformat(),
        region,
        species,
        latin_name,
    )


def sighting_dict(sighting: Sighting) -> dict[str, Any]:
    """Convert a normalized sighting to a database-ready mapping."""
    return asdict(sighting)
