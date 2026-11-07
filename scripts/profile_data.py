"""Profile a saved JSON list and write a compact data quality report."""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

DEFAULT_SAMPLE = Path("docs/samples/sightings-all.json")
DEFAULT_REPORT = Path("docs/data-quality-report.md")
IDENTIFIER_FIELDS = {"id", "date", "observed_at"}


def json_type(value: Any) -> str:
    """Return a stable JSON-style type name for a Python value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _categorical_fields(rows: list[dict[str, Any]]) -> list[str]:
    """Infer string categories by excluding identifiers and high-cardinality fields."""
    fields = sorted({key for row in rows for key in row} - IDENTIFIER_FIELDS)
    threshold = max(50, len(rows) // 20)
    return [
        field
        for field in fields
        if len({str(row[field]) for row in rows if isinstance(row.get(field), str)})
        <= threshold
    ]


def _format_class(value: Any) -> str:
    """Classify common source date representations without losing the raw value."""
    if not isinstance(value, str):
        return "non-string"
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return "invalid"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return "ISO date"
    if "T" in value or " " in value:
        if value.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", value):
            return "ISO datetime with timezone"
        return "ISO datetime without timezone"
    return "other parseable date"


def _text_variants(
    values: Counter[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Find case/space variants and likely spelling variants in category labels."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for value in values:
        canonical = " ".join(value.split()).casefold()
        grouped[canonical].append(value)
    normalized = [
        {
            "values": {value: values[value] for value in variants},
            "rows": sum(values[v] for v in variants),
        }
        for variants in grouped.values()
        if len(variants) > 1
    ]
    labels = list(values)
    spelling = []
    used_pairs: set[tuple[str, str]] = set()
    for index, first in enumerate(labels):
        first_key = " ".join(first.split()).casefold()
        for second in labels[index + 1 :]:
            second_key = " ".join(second.split()).casefold()
            if first_key == second_key or min(len(first_key), len(second_key)) < 5:
                continue
            if SequenceMatcher(None, first_key, second_key).ratio() < 0.9:
                continue
            pair = tuple(sorted((first, second)))
            if pair in used_pairs:
                continue
            used_pairs.add(pair)
            spelling.append(
                {
                    "values": {first: values[first], second: values[second]},
                    "rows": values[first] + values[second],
                }
            )
    return normalized, spelling


def profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute schema, categories, date formats, and observed quality issues."""
    fields = sorted({key for row in rows for key in row})
    categorical_fields = _categorical_fields(rows)
    field_types = {
        key: dict(sorted(Counter(json_type(row.get(key)) for row in rows).items()))
        for key in fields
    }
    null_counts = {key: sum(row.get(key) is None for row in rows) for key in fields}
    categories = {
        key: dict(
            sorted(
                Counter(
                    str(row[key]) for row in rows if row.get(key) is not None
                ).items()
            )
        )
        for key in categorical_fields
    }
    category_variants = {}
    spelling_variants = {}
    for field, counts in categories.items():
        normalized, spelling = _text_variants(Counter(counts))
        category_variants[field] = normalized
        spelling_variants[field] = spelling

    date_formats = Counter(_format_class(row.get("date")) for row in rows)
    date_values = []
    invalid_dates = 0
    invalid_date_examples = []
    timezone_naive_dates = 0
    for row in rows:
        try:
            parsed = datetime.fromisoformat(str(row["date"]))
            if parsed.tzinfo is None:
                timezone_naive_dates += 1
                parsed = parsed.replace(tzinfo=UTC)
            date_values.append(parsed.astimezone(UTC))
        except (KeyError, TypeError, ValueError):
            invalid_dates += 1
            if len(invalid_date_examples) < 3:
                invalid_date_examples.append(str(row.get("date")))

    duplicate_keys = Counter(
        (
            str(row.get("date", "")),
            " ".join(
                str(row.get("location", row.get("region", ""))).split()
            ).casefold(),
            " ".join(str(row.get("species", "")).split()).casefold(),
        )
        for row in rows
    )
    duplicate_groups = {
        key: count for key, count in duplicate_keys.items() if count > 1
    }
    species_latin_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row.get("species") is not None and row.get("latinName") is not None:
            species_latin_counts[str(row["species"])][str(row["latinName"])] += 1
    mismatch_examples = []
    mismatch_count = 0
    for species, pairs in species_latin_counts.items():
        expected = pairs.most_common(1)[0][0]
        for latin_name, count in pairs.items():
            if latin_name != expected:
                mismatch_count += count
                mismatch_examples.append(
                    f"{species} → {latin_name} (expected {expected})"
                )

    format_total = sum(date_formats.values())
    canonical_format = date_formats.most_common(1)[0][0] if date_formats else "none"
    format_variant_count = format_total - date_formats.get(canonical_format, 0)
    normalized_variant_count = sum(
        issue["rows"] for issues in category_variants.values() for issue in issues
    )
    spelling_variant_count = sum(
        issue["rows"] for issues in spelling_variants.values() for issue in issues
    )
    return {
        "row_count": len(rows),
        "field_names": fields,
        "field_types": field_types,
        "null_counts": null_counts,
        "categorical_fields": categorical_fields,
        "categorical_values": categories,
        "category_variants": category_variants,
        "spelling_variants": spelling_variants,
        "date_format_counts": dict(sorted(date_formats.items())),
        "timezone_naive_date_rows": timezone_naive_dates,
        "date_coverage": {
            "minimum": min(date_values).isoformat() if date_values else None,
            "maximum": max(date_values).isoformat() if date_values else None,
            "invalid_count": invalid_dates,
        },
        "invalid_date_examples": invalid_date_examples,
        "duplicate_content_groups": len(duplicate_groups),
        "duplicate_content_rows": sum(count - 1 for count in duplicate_groups.values()),
        "duplicate_content_examples": [
            {"date": key[0], "city": key[1], "species": key[2], "count": count}
            for key, count in list(duplicate_groups.items())[:3]
        ],
        "species_latin_mismatch_rows": mismatch_count,
        "species_latin_mismatch_examples": mismatch_examples,
        "issue_counts": {
            "case_or_whitespace_variant_rows": normalized_variant_count,
            "spelling_variant_rows": spelling_variant_count,
            "date_format_variant_rows": format_variant_count,
            "timezone_naive_date_rows": timezone_naive_dates,
            "invalid_date_rows": invalid_dates,
            "duplicate_content_rows": sum(
                count - 1 for count in duplicate_groups.values()
            ),
            "species_latin_mismatch_rows": mismatch_count,
        },
    }


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a Markdown table and escape cell delimiters."""
    safe_rows = [
        [cell.replace("|", "\\|").replace("\n", " ") for cell in row] for row in rows
    ]
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *["| " + " | ".join(row) + " |" for row in safe_rows],
        ]
    )


def render_report(result: dict[str, Any]) -> str:
    """Build the required issue table plus detailed categorical frequencies."""
    category_examples = {
        field: issues for field, issues in result["category_variants"].items() if issues
    }
    spelling_examples = {
        field: issues for field, issues in result["spelling_variants"].items() if issues
    }
    issues = [
        [
            "Case or whitespace category variants",
            str(result["issue_counts"]["case_or_whitespace_variant_rows"]),
            json.dumps(category_examples, ensure_ascii=False)
            if category_examples
            else "None found",
            "Normalize whitespace and known category casing; preserve unknown labels.",
        ],
        [
            "Likely spelling variants",
            str(result["issue_counts"]["spelling_variant_rows"]),
            json.dumps(spelling_examples, ensure_ascii=False)
            if spelling_examples
            else "None found",
            "Quarantine likely typos and preserve the raw payload for review.",
        ],
        [
            "Date format variants",
            str(result["issue_counts"]["date_format_variant_rows"]),
            json.dumps(result["date_format_counts"], ensure_ascii=False),
            "Normalize parseable timestamps to UTC ISO 8601; quarantine invalid dates.",
        ],
        [
            "Timezone-naive timestamps",
            str(result["timezone_naive_date_rows"]),
            "ISO datetime without timezone",
            "Interpret timezone-naive source dates as UTC and store UTC ISO 8601.",
        ],
        [
            "Invalid dates",
            str(result["issue_counts"]["invalid_date_rows"]),
            "; ".join(result["invalid_date_examples"]) or "None found",
            "Quarantine the record and retain its original JSON payload.",
        ],
        [
            "Duplicate (date, city, species) content rows",
            str(result["issue_counts"]["duplicate_content_rows"]),
            json.dumps(result["duplicate_content_examples"], ensure_ascii=False)
            if result["duplicate_content_examples"]
            else "None found",
            "Keep source IDs as authoritative; log duplicate content tuples and do not merge distinct IDs.",
        ],
        [
            "Species and latinName mismatches",
            str(result["issue_counts"]["species_latin_mismatch_rows"]),
            "; ".join(result["species_latin_mismatch_examples"]) or "None found",
            "Quarantine mismatches against the observed species-to-Latin-name crosswalk.",
        ],
    ]
    category_rows = [
        [field, value, str(count)]
        for field, values in result["categorical_values"].items()
        for value, count in values.items()
    ]
    format_rows = [
        [key, str(value)] for key, value in result["date_format_counts"].items()
    ]
    return "\n".join(
        [
            "# Data quality report",
            "",
            f"Profiled {result['row_count']} rows from `docs/samples/sightings-all.json`.",
            "",
            _markdown_table(["Issue", "Count", "Example", "Handling rule"], issues),
            "",
            "## Categorical values and counts",
            "",
            _markdown_table(["Field", "Value", "Rows"], category_rows),
            "",
            "## Date formats",
            "",
            _markdown_table(["Format", "Rows"], format_rows),
            "",
            "## Schema profile",
            "",
            f"Fields: `{', '.join(result['field_names'])}`. Types: `{json.dumps(result['field_types'], sort_keys=True)}`.",
            f"Null counts: `{json.dumps(result['null_counts'], sort_keys=True)}`.",
            f"Date coverage: `{result['date_coverage']['minimum']}` through `{result['date_coverage']['maximum']}`.",
            "",
        ]
    )


def main() -> None:
    """Profile a saved JSON list and write the Markdown report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", nargs="?", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    rows = json.loads(args.sample.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise SystemExit("sample must contain a JSON array of objects")
    result = profile(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_report(result), encoding="utf-8")
    print(
        json.dumps({"report": str(args.output), **result}, indent=2, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
