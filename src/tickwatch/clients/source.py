"""HTTP client for the external sightings source."""

import random
import time
from collections.abc import Iterator
from typing import Any

import httpx

from tickwatch.core.exceptions import UpstreamAPIError


class SourceClient:
    """Fetch source pages with bounded retries and page streaming."""

    def __init__(
        self,
        url: str,
        timeout: float = 10.0,
        attempts: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Configure an injectable synchronous HTTP client."""
        self.url, self.attempts = url, max(1, attempts)
        self.client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        """Release the underlying connection pool."""
        self.client.close()

    def _get(self, url: str) -> httpx.Response:
        """Retry only transient transport, throttling, and server failures."""
        for attempt in range(self.attempts):
            try:
                response = self.client.get(url)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        "retryable response",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response
            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.HTTPStatusError,
            ) as error:
                retryable = (
                    not isinstance(error, httpx.HTTPStatusError)
                    or error.response.status_code == 429
                    or error.response.status_code >= 500
                )
                if not retryable or attempt + 1 == self.attempts:
                    raise UpstreamAPIError(
                        "source request failed after retries"
                    ) from error
                time.sleep(min(2**attempt + random.random(), 8))
        raise UpstreamAPIError("source request failed")

    def pages(self) -> Iterator[list[dict[str, Any]]]:
        """Yield the API's complete list response as one batch."""
        payload = self._get(self.url).json()
        if not isinstance(payload, list) or not all(
            isinstance(row, dict) for row in payload
        ):
            raise UpstreamAPIError("source response must be a list of sighting objects")
        if payload:
            yield payload
