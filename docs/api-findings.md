# Live API findings

## Discovery

The root URL serves a client-rendered Next.js documentation shell. Its `/docs` and `/openapi.json` paths return 404. `__ENV.js` sets `REACT_APP_API_URL` to `https://dev-task.elancoapps.com/api-service` and sets authentication to `true`; direct requests to that prefix returned 404. The page's `index-63e8627b3ab3ed26.js` chunk embeds an OpenAPI 3.0.3 document whose server is `/data`. That document says all routes are public GET requests and require no key. Direct probes confirmed the API is served from `https://dev-task.elancoapps.com/data` without an auth header.

All five candidate spec paths (`/openapi.json`, `/swagger.json`, `/api-docs`, `/api/openapi.json`, `/v1/openapi.json`) returned 404 both under `/api-service` and under `/data`. The spec embedded in the page bundle is therefore the available route description.

## Verified endpoint contract

| Request | Status | Body shape and observation |
|---|---:|---|
| `GET /data/` | 200 | `{"message": "Welcome to the Tick Sightings API"}` |
| `GET /data/health` | 200 | `{"status": "healthy"}` |
| `GET /data/stats` | 200 | `{"api_version": "1.0.0", "total_sightings": 1000}` |
| `GET /data/tick-sightings` | 200 | Array of 1,000 sighting objects |
| `GET /data/tick-sightings/{sighting_id}` | 200 for known ID | One sighting object |
| `GET /data/tick-sightings/does-not-exist` | 404 | `{"error": "Not found"}` |
| `GET /data/tick-sightings/city/Manchester` | 200 | Array of 72 sightings |
| `GET /data/tick-sightings/species/Marsh%20tick` | 200 | Array of 186 sightings |

The list endpoint has no documented paging parameters. Requests with `limit=50&offset=0`, `limit=50&offset=475`, and `limit=50&offset=950` each returned the same 1,000 rows; the server ignores those parameters. Ingestion therefore makes one request and consumes the complete returned array.

List records have exactly five fields: `id`, `date`, `latinName`, `location`, and `species`. All are non-null strings in the observed dataset. The `date` values are ISO-like timestamps without an offset; ingestion treats these naive values as UTC when normalizing. No coordinates or severity field are provided.

## Data profile

Run `python scripts/profile_data.py` to profile the saved raw list response. The captured response contains 1,000 rows, 1,000 distinct IDs, zero nulls, and a date range of `2012-01-03T20:40:43` to `2024-12-30T04:32:12`.

Distinct categories: 5 species, 5 Latin names, and 14 locations. Species counts are Fox/badger tick 210, Marsh tick 186, Passerine tick 226, Southern rodent tick 192, and Tree-hole tick 186. The complete field frequency profile is in the script output.

## Samples

Raw response bodies and request/status notes are in [`samples/README.md`](samples/README.md). The three paging probes are retained separately even though the upstream returned identical full arrays. The list endpoint's source IDs are kept as local primary keys; fallback hashing is used only when an ID is missing.
