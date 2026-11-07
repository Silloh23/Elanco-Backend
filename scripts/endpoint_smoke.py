"""Smoke-test every public API route with a valid and invalid request."""

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True)
class SmokeResult:
    """One request's expected status and concise observed result."""

    case: str
    method: str
    path: str
    status: int
    expected: int
    elapsed_ms: float
    snippet: str


def _request(client: httpx.Client, case: str, path: str, expected: int) -> SmokeResult:
    """Issue a GET request and retain its first 100 response characters."""
    started = time.perf_counter()
    response = client.get(path)
    elapsed_ms = (time.perf_counter() - started) * 1000
    snippet = (response.text[:100] or "<empty>").replace("\n", " ").replace("|", "\\|")
    return SmokeResult(
        case, "GET", path, response.status_code, expected, elapsed_ms, snippet
    )


def run_smoke(base_url: str) -> list[SmokeResult]:
    """Call each business route once successfully and once with invalid input."""
    results: list[SmokeResult] = []
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=10.0) as client:
        started = time.perf_counter()
        list_response = client.get("/sightings?limit=1")
        elapsed_ms = (time.perf_counter() - started) * 1000
        snippet = (
            (list_response.text[:100] or "<empty>")
            .replace("\n", " ")
            .replace("|", "\\|")
        )
        results.append(
            SmokeResult(
                "valid",
                "GET",
                "/sightings?limit=1",
                list_response.status_code,
                200,
                elapsed_ms,
                snippet,
            )
        )
        sightings = list_response.json()
        items = sightings.get("items", [])
        if not items:
            raise RuntimeError(
                "cannot smoke-test sighting lookup: database has no rows"
            )
        sighting_id = str(items[0]["id"])

        cases = [
            ("valid", "/health", 200),
            ("invalid", "/health/not-a-route", 404),
            ("invalid", "/sightings?start_date=not-a-date", 422),
            ("valid", f"/sightings/{sighting_id}", 200),
            ("invalid", "/sightings/not-a-real-id", 404),
            ("valid", "/analytics/by-region?species=Marsh%20tick", 200),
            ("invalid", "/analytics/by-region?start_date=not-a-date", 422),
            ("valid", "/analytics/by-species", 200),
            ("invalid", "/analytics/by-species/not-a-route", 404),
            ("valid", "/analytics/trends?granularity=monthly", 200),
            ("invalid", "/analytics/trends?granularity=annual", 422),
            ("valid", "/insights/anomalies?region=Manchester", 200),
            ("invalid", "/insights/anomalies?region=No%20Such%20City", 422),
            ("valid", "/insights/forecast?region=Manchester", 200),
            ("invalid", "/insights/forecast?region=No%20Such%20City", 422),
            (
                "valid",
                "/insights/seasonality?city=Manchester&species=Marsh%20tick",
                200,
            ),
            ("invalid", "/insights/seasonality/not-a-route", 404),
        ]
        results.extend(
            _request(client, case, path, expected) for case, path, expected in cases
        )
    return results


def render(results: list[SmokeResult]) -> str:
    """Render request outcomes as the checked-in Markdown smoke table."""
    rows = [
        "# Endpoint smoke results",
        "",
        "Run with `uv run python scripts/endpoint_smoke.py --output docs/endpoint-smoke.md`.",
        "",
        "| Case | Method | Path | Status | Time (ms) | First 100 response characters | Result |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for result in results:
        verdict = "PASS" if result.status == result.expected else "FAIL"
        rows.append(
            f"| {result.case} | {result.method} | `{result.path}` | {result.status} "
            f"(expected {result.expected}) | {result.elapsed_ms:.1f} | "
            f"`{result.snippet}` | {verdict} |"
        )
    passed = sum(result.status == result.expected for result in results)
    rows.extend(["", f"Passed {passed}/{len(results)} requests.", ""])
    return "\n".join(rows)


def main() -> None:
    """Run endpoint smoke requests and optionally save their Markdown report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = run_smoke(args.base_url)
    report = render(results)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    print(report)
    if any(result.status != result.expected for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
