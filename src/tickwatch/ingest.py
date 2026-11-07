"""Command-line entry point for source ingestion."""

import logging

from tickwatch.clients.source import SourceClient
from tickwatch.core.config import Settings
from tickwatch.core.logging_config import configure_logging
from tickwatch.services.ingestion import ingest


def main() -> None:
    """Run one ingestion and log its summary through standard output."""
    settings = Settings()
    client = SourceClient(
        settings.api_url, settings.request_timeout, settings.retry_attempts
    )
    try:
        configure_logging()
        logging.getLogger("tickwatch.ingest").info(
            "ingestion_complete", extra=ingest(client, settings.database_path)
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()
