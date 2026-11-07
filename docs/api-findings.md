# API discovery findings

## Probe status

The configured source is `https://dev-task.elancoapps.com/`. From this workspace, DNS lookup fails (`curl: (6) Could not resolve host`). The browsing tool also reports the host inaccessible. Therefore no HTTP response, docs, endpoint list, headers, or sample records could be observed. No live API facts are inferred or fabricated.

## Current integration contract

The client requests the configured base URL and accepts either a JSON list, an object containing `results`/`data`/`items`, or a single record object. It follows a response `next` URL if present, otherwise increments an `offset` parameter when `count` indicates more records. This is a provisional compatibility strategy, not verified source behavior. Endpoint path, auth, pagination, rate limits, field schema, volume, and response shape must be verified when the host is reachable.

## Data quality evidence

Live sample count: 0 (source unreachable). Missing/null fields, duplicates, format inconsistencies, outliers and their frequencies cannot be measured. Ingestion quarantines unrecognized or invalid records with the raw JSON and reason to prevent silent data loss. The cleaner supports common date, region, species, and coordinate field aliases pending schema confirmation.
