# Decisions

- **Stack:** FastAPI, Pydantic, httpx and stdlib sqlite3 follow the task's fixed, explainable stack. Repositories isolate SQL so a future Postgres migration does not affect services.
- **Source contract:** The client targets the verified `/data/tick-sightings` list, which returns the full list in one response and ignores offset/limit parameters. The client is kept configurable in case the upstream route changes.
- **Dedupe key:** Keep the source `id` as the primary key. If a record has no ID, hash its normalized UTC date, location, species, and Latin name. This fallback can merge indistinguishable reports.
- **Cleaning:** Map `date`, `location`, and `latinName` to the local observed time, region, and Latin name fields; normalize timestamps to UTC and collapse whitespace while preserving species casing. The source has no coordinate fields, so geographic radius queries are not offered. Preserve rejected raw payloads in quarantine.
- **Storage:** SQLite for a small MVP with no external service requirement. Its single-writer limits make Postgres preferable at higher ingest concurrency/volume.
- **SQL:** Parameterized SQL in typed repository classes keeps queries inspectable and avoids ORM indirection.
- **Indexes:** Date, region, and species indexes support the primary filters and analytics groupings.
- **Insight granularity:** Monthly is the default because the source data spans years and city-level monthly series are already sparse. Weekly remains an explicit option.
- **Minimum insight data:** Anomaly and forecast routes require at least nine non-zero periods; otherwise they return HTTP 422 with the observed and required counts. Nine provides an eight-period anomaly baseline plus a target period.
- **Seasonality:** Report mean count for each calendar month over the selected series' covered years, counting missing months inside that range as zero. Months outside its coverage have no average.
- **Seasonality significance test:** Test the null that daily sighting rates are equal across calendar months. Expected monthly counts are weighted by the number of calendar days in the covered months, including leap days; the API reports Pearson chi-square, degrees of freedom, p-value, and a 5% verdict. Per-species results also report the Bonferroni-adjusted threshold, using the number of observed species as the test family. A pure-Python regularized upper incomplete gamma calculation avoids a SciPy dependency. The test assumes independent counts; repeated sightings, reporting effort, and temporal clustering can violate that assumption, so the results are descriptive rather than causal.
- **Anomalies:** Rolling mean and population standard deviation produce an understandable z-score over the selected monthly or weekly series.
- **Forecast:** Repeat the latest four observed monthly counts by default, with weekly periods optional. This is a short naive baseline, not a predictive model.
