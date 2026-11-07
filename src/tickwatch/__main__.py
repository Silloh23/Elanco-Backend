"""Run the local development server."""

import uvicorn

from tickwatch.core.logging_config import configure_logging


def main() -> None:
    """Start the FastAPI application."""
    configure_logging()
    uvicorn.run("tickwatch.api.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
