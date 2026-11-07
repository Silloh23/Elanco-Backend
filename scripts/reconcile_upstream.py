"""Compare local sighting aggregates with the public upstream API."""

import argparse
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from tickwatch.core.config import Settings
from tickwatch.repositories.database import connect
from tickwatch.repositories.sightings import SightingRepository


def _get_json(client: httpx.Client, url: str) -> Any:
    """Fetch JSON and fail clearly for a non-success API response."""
    response = client.get(url)
    response.raise_for_status()
    return response.json()


def reconcile(
    database_path: str,
    api_url: str,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Compare local totals, city counts, and species counts to upstream routes."""
    connection = connect(database_path)
    local = SightingRepository(connection).reconciliation_aggregates()
    connection.close()
    base_url = api_url.rsplit("/", 1)[0].rstrip("/")
    with httpx.Client(timeout=20.0, transport=transport) as client:
        stats = _get_json(client, f"{base_url}/stats")
        source_rows = _get_json(client, api_url)
        if not isinstance(source_rows, list) or not all(
            isinstance(row, dict) for row in source_rows
        ):
            raise ValueError(
                "upstream list endpoint did not return a JSON object array"
            )
        cities = set(local["cities"]) | {
            str(row["location"])
            for row in source_rows
            if row.get("location") is not None
        }
        species_names = set(local["species"]) | {
            str(row["species"]) for row in source_rows if row.get("species") is not None
        }
        upstream_cities = {
            city: len(
                _get_json(
                    client,
                    f"{base_url}/tick-sightings/city/{quote(city, safe='')}",
                )
            )
            for city in sorted(cities)
        }
        upstream_species = {
            species: len(
                _get_json(
                    client,
                    f"{base_url}/tick-sightings/species/{quote(species, safe='')}",
                )
            )
            for species in sorted(species_names)
        }

    comparisons = [
        {
            "dimension": "total",
            "value": "all",
            "local": local["total"],
            "upstream": int(stats["total_sightings"]),
        }
    ]
    comparisons.extend(
        {
            "dimension": "city",
            "value": city,
            "local": int(local["cities"].get(city, 0)),
            "upstream": upstream_cities[city],
        }
        for city in sorted(cities)
    )
    comparisons.extend(
        {
            "dimension": "species",
            "value": name,
            "local": int(local["species"].get(name, 0)),
            "upstream": upstream_species[name],
        }
        for name in sorted(species_names)
    )
    differences = [
        {**row, "difference": row["local"] - row["upstream"]}
        for row in comparisons
        if row["local"] != row["upstream"]
    ]
    return {"comparisons": comparisons, "differences": differences}


def main() -> None:
    """Run reconciliation and print only mismatches plus total comparison."""
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(settings.database_path))
    parser.add_argument("--api-url", default=settings.api_url)
    args = parser.parse_args()
    result = reconcile(str(args.database), args.api_url)
    total = result["comparisons"][0]
    print(
        f"Total: local={total['local']} upstream={total['upstream']} "
        f"difference={total['local'] - total['upstream']}"
    )
    if result["differences"]:
        print("Differences (local - upstream):")
        for row in result["differences"]:
            print(
                f"{row['dimension']} {row['value']}: local={row['local']} "
                f"upstream={row['upstream']} difference={row['difference']}"
            )
    else:
        print("No differences detected across total, city, and species counts.")


if __name__ == "__main__":
    main()
