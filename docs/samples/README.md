# Captured API samples

- `root.json` — successful response from the source API root.
- `health.json` — successful health response.
- `stats.json` — successful API statistics response.
- `sightings-all.json` — first ten records from the original 1,000-record response; deliberately truncated.
- `sightings-page-sample.json` — ten-record sample from the paging probes.
- `sightings-city-manchester.json` — first five Manchester sightings.
- `sightings-species-marsh-tick.json` — first five Marsh tick sightings.
- `sighting-by-id.json` — successful single-sighting response.
- `sighting-not-found.json` — not-found response for an unknown sighting ID.
- `openapi.json` — valid OpenAPI 3.0.3 document embedded in the documentation site's JavaScript bundle.

The API ignores `limit` and `offset`; the first, middle, and last paging requests returned identical arrays, so only one ten-record page sample is kept.
