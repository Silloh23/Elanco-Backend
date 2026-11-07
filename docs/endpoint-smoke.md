# Endpoint smoke results

Run with `uv run python scripts/endpoint_smoke.py --output docs/endpoint-smoke.md`.

| Case | Method | Path | Status | Time (ms) | First 100 response characters | Result |
|---|---|---|---:|---:|---|---|
| valid | GET | `/sightings?limit=1` | 200 (expected 200) | 28.5 | `{"items":[{"id":"vu9k3oRyy2BQskX6rBO9","observed_at":"2012-01-03T20:40:43+00:00","region":"Edinburgh` | PASS |
| valid | GET | `/health` | 200 (expected 200) | 2.7 | `{"status":"ok"}` | PASS |
| invalid | GET | `/health/not-a-route` | 404 (expected 404) | 1.0 | `{"detail":"Not Found"}` | PASS |
| invalid | GET | `/sightings?start_date=not-a-date` | 422 (expected 422) | 1.8 | `{"error":{"code":"validation_error","message":"[{'type': 'date_from_datetime_parsing', 'loc': ('quer` | PASS |
| valid | GET | `/sightings/vu9k3oRyy2BQskX6rBO9` | 200 (expected 200) | 1.5 | `{"id":"vu9k3oRyy2BQskX6rBO9","observed_at":"2012-01-03T20:40:43+00:00","region":"Edinburgh","species` | PASS |
| invalid | GET | `/sightings/not-a-real-id` | 404 (expected 404) | 1.1 | `{"error":{"code":"not_found","message":"sighting not found"}}` | PASS |
| valid | GET | `/analytics/by-region?species=Marsh%20tick` | 200 (expected 200) | 1.5 | `{"items":[{"region":"Birmingham","count":13},{"region":"Bristol","count":16},{"region":"Cardiff","co` | PASS |
| invalid | GET | `/analytics/by-region?start_date=not-a-date` | 422 (expected 422) | 0.7 | `{"error":{"code":"validation_error","message":"[{'type': 'date_from_datetime_parsing', 'loc': ('quer` | PASS |
| valid | GET | `/analytics/by-species` | 200 (expected 200) | 1.5 | `{"items":[{"species":"Passerine tick","count":226,"share_percent":22.6},{"species":"Fox/badger tick"` | PASS |
| invalid | GET | `/analytics/by-species/not-a-route` | 404 (expected 404) | 0.8 | `{"detail":"Not Found"}` | PASS |
| valid | GET | `/analytics/trends?granularity=monthly` | 200 (expected 200) | 2.6 | `{"granularity":"monthly","items":[{"period":"2012-01-01","count":9},{"period":"2012-02-01","count":9` | PASS |
| invalid | GET | `/analytics/trends?granularity=annual` | 422 (expected 422) | 0.9 | `{"error":{"code":"validation_error","message":"granularity must be weekly or monthly"}}` | PASS |
| valid | GET | `/insights/anomalies?region=Manchester` | 200 (expected 200) | 3.6 | `{"region":"Manchester","granularity":"monthly","items":[{"period":"2012-11-01","index":10,"count":2,` | PASS |
| invalid | GET | `/insights/anomalies?region=No%20Such%20City` | 422 (expected 422) | 1.1 | `{"error":{"code":"insufficient_data","message":"This insight requires more periods with sightings.",` | PASS |
| valid | GET | `/insights/forecast?region=Manchester` | 200 (expected 200) | 1.5 | `{"region":"Manchester","granularity":"monthly","method":"naive: repeat latest four observed monthly ` | PASS |
| invalid | GET | `/insights/forecast?region=No%20Such%20City` | 422 (expected 422) | 1.1 | `{"error":{"code":"insufficient_data","message":"This insight requires more periods with sightings.",` | PASS |
| valid | GET | `/insights/seasonality?city=Manchester&species=Marsh%20tick` | 200 (expected 200) | 1.9 | `{"city":"Manchester","species":"Marsh tick","items":[{"month":1,"month_name":"January","average_coun` | PASS |
| invalid | GET | `/insights/seasonality/not-a-route` | 404 (expected 404) | 0.6 | `{"detail":"Not Found"}` | PASS |

Passed 18/18 requests.
