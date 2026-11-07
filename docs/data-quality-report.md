# Data quality report

The findings below describe the original 1,000-row API response, profiled before the repository sample was trimmed. `docs/samples/sightings-all.json` now contains only its first 10 records; the current sample cannot reproduce the full profile.

| Issue | Count | Example | Handling rule |
| --- | --- | --- | --- |
| Case or whitespace category variants | 0 | None found | Normalize whitespace and known category casing; preserve unknown labels. |
| Likely spelling variants | 0 | None found | Quarantine likely typos and preserve the raw payload for review. |
| Date format variants | 0 | {"ISO datetime without timezone": 1000} | Normalize parseable timestamps to UTC ISO 8601; quarantine invalid dates. |
| Timezone-naive timestamps | 1000 | ISO datetime without timezone | Interpret timezone-naive source dates as UTC and store UTC ISO 8601. |
| Invalid dates | 0 | None found | Quarantine the record and retain its original JSON payload. |
| Duplicate (date, city, species) content rows | 0 | None found | Keep source IDs as authoritative; log duplicate content tuples and do not merge distinct IDs. |
| Species and latinName mismatches | 0 | None found | Quarantine mismatches against the observed species-to-Latin-name crosswalk. |

## Categorical values and counts

| Field | Value | Rows |
| --- | --- | --- |
| latinName | Dermacentor frontalis | 226 |
| latinName | Ixodes acuminatus | 192 |
| latinName | Ixodes apronophorus | 186 |
| latinName | Ixodes arboricola | 186 |
| latinName | Ixodes canisuga | 210 |
| location | Birmingham | 82 |
| location | Bristol | 77 |
| location | Cardiff | 71 |
| location | Edinburgh | 73 |
| location | Glasgow | 78 |
| location | Leeds | 59 |
| location | Leicester | 61 |
| location | Liverpool | 73 |
| location | London | 76 |
| location | Manchester | 72 |
| location | Newcastle | 57 |
| location | Nottingham | 95 |
| location | Sheffield | 69 |
| location | Southampton | 57 |
| species | Fox/badger tick | 210 |
| species | Marsh tick | 186 |
| species | Passerine tick | 226 |
| species | Southern rodent tick | 192 |
| species | Tree-hole tick | 186 |

## Date formats

| Format | Rows |
| --- | --- |
| ISO datetime without timezone | 1000 |

## Schema profile

Fields: `date, id, latinName, location, species`. Types: `{"date": {"string": 1000}, "id": {"string": 1000}, "latinName": {"string": 1000}, "location": {"string": 1000}, "species": {"string": 1000}}`.
Null counts: `{"date": 0, "id": 0, "latinName": 0, "location": 0, "species": 0}`.
Date coverage: `2012-01-03T20:40:43+00:00` through `2024-12-30T04:32:12+00:00`.
