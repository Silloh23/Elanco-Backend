# Decisions

- **Stack:** FastAPI, Pydantic, httpx and stdlib sqlite3 follow the task's fixed, explainable stack. Repositories isolate SQL so a future Postgres migration does not affect services.
- **Source contract:** The client targets the verified `/data/tick-sightings` list, which returns the full list in one response and ignores offset/limit parameters. The client is kept configurable in case the upstream route changes.
- **Dedupe key:** Keep the source `id` as the primary key. If a record has no ID, hash its normalized UTC date, location, species, and Latin name. This fallback can merge indistinguishable reports.
- **Cleaning:** Map `date`, `location`, and `latinName` to the local observed time, region, and Latin name fields; normalize timestamps to UTC and collapse whitespace while preserving species casing. The source has no coordinate fields, so geographic radius queries are not offered. Preserve rejected raw payloads in quarantine.
- **Storage:** SQLite for a small MVP with no external service requirement. Its single-writer limits make Postgres preferable at higher ingest concurrency/volume.
- **SQL:** Parameterized SQL in typed repository classes keeps queries inspectable and avoids ORM indirection.
- **Indexes:** Date, region, and species indexes support the primary filters and analytics groupings.
- **Anomalies:** Rolling mean and population standard deviation produce an understandable z-score; sparse and flat baselines are suppressed to avoid false certainty.
- **Forecast:** A seasonal naive weekly baseline repeats the most recent four observed weeks. It is a simple reference forecast, not a predictive model.
