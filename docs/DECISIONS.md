# Decisions

- **Stack:** FastAPI, Pydantic, httpx and stdlib sqlite3 follow the task's fixed, explainable stack. Repositories isolate SQL so a future Postgres migration does not affect services.
- **Source assumptions:** Live API discovery was impossible because this execution environment could not resolve the host. The base URL is configurable; response pagination and field aliases are provisional and documented in `api-findings.md`.
- **Dedupe key:** SHA-256 over canonical UTC timestamp, normalized region, normalized species, and rounded coordinates. Upstream IDs are preferred when present. Since no sample data was available, this natural-key choice is a defensible fallback and may merge genuinely separate sightings with identical reported values.
- **Cleaning:** Normalize common date formats to UTC; lowercase/trim/collapse whitespace in species and region; validate UK coordinate envelope. Preserve all rejected raw payloads in quarantine.
- **Storage:** SQLite for a small MVP with no external service requirement. Its single-writer limits make Postgres preferable at higher ingest concurrency/volume.
- **SQL:** Parameterized SQL in typed repository classes keeps queries inspectable and avoids ORM indirection.
- **Indexes:** Date, region, and species indexes support the primary filters and analytics groupings.
- **Anomalies:** Rolling mean and population standard deviation produce an understandable z-score; sparse and flat baselines are suppressed to avoid false certainty.
- **Forecast:** A seasonal naive weekly baseline repeats the most recent four observed weeks. It is a simple reference forecast, not a predictive model.
