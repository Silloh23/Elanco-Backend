"""HTTP client for the external sightings source."""

import random
import time
from collections.abc import Iterator
from typing import Any

import httpx

from tickwatch.core.exceptions import UpstreamAPIError


class SourceClient:
    """Fetch source pages with bounded retries and page streaming."""

    def __init__(self, url: str, timeout: float = 10.0, attempts: int = 3,
                 transport: httpx.BaseTransport | None = None) -> None:
        """Configure an injectable synchronous HTTP client."""
        self.url, self.attempts = url, max(1, attempts)
        self.client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        """Release the underlying connection pool."""
        self.client.close()

    def _get(self, url: str, params: dict[str, Any] | None) -> httpx.Response:
        """Retry only transient transport, throttling, and server failures."""
        for attempt in range(self.attempts):
            try:
                response = self.client.get(url, params=params)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError("retryable response", request=response.request, response=response)
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as error:
                retryable = not isinstance(error, httpx.HTTPStatusError) or error.response.status_code == 429 or error.response.status_code >= 500
                if not retryable or attempt + 1 == self.attempts:
                    raise UpstreamAPIError("source request failed after retries") from error
                time.sleep(min(2 ** attempt + random.random(), 8))
        raise UpstreamAPIError("source request failed")

    def pages(self) -> Iterator[list[dict[str, Any]]]:
        """Yield source records page by page without retaining the full dataset."""
        url, offset = self.url, 0
        params: dict[str, Any] | None = {"offset": offset}
        while url:
            payload = self._get(url, params).json()
            if isinstance(payload, list):
                rows, next_url = payload, None
            elif isinstance(payload, dict):
                rows = payload.get("results", payload.get("data", payload.get("items", [])))
                next_url = payload.get("next")
                if not rows and any(key in payload for key in ("id", "sighting_id")):
                    rows = [payload]
            else:
                raise UpstreamAPIError("source returned an unexpected JSON shape")
            if not isinstance(rows, list):
                raise UpstreamAPIError("source page does not contain a record list")
            if rows:
                yield rows
            if next_url:
                url, params = str(next_url), None
            elif isinstance(payload, dict) and payload.get("count") is not None and rows:
                offset += len(rows)
                params = {"offset": offset}
                url = self.url if offset < int(payload["count"]) else ""
            else:
                url = ""
