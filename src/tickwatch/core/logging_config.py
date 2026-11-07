"""One-time standard-library logging configuration."""

import logging


def configure_logging() -> None:
    """Set a consistent format for service lifecycle and failure messages."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
