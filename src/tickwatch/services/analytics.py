"""SQL-backed aggregate query construction."""

from typing import Any


def filter_sql(
    start_date: str | None,
    end_date: str | None,
    region: str | None,
    species: str | None,
) -> tuple[str, list[Any]]:
    """Build parameterized shared filters for sightings aggregates."""
    clauses, values = [], []
    for column, value, operator in (
        ("observed_at", start_date, ">="),
        ("observed_at", end_date, "<="),
        ("region", region, "="),
        ("species", species, "="),
    ):
        if value is not None:
            clauses.append(f"{column} {operator} ?")
            values.append(value)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), values
