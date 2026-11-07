"""Application settings loaded from environment variables."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Central configuration shared by application layers."""

    api_url: str = os.getenv(
        "TICKWATCH_API_URL",
        "https://dev-task.elancoapps.com/data/tick-sightings",
    )
    database_path: str = os.getenv("TICKWATCH_DATABASE_PATH", "tickwatch.db")
    request_timeout: float = float(os.getenv("TICKWATCH_REQUEST_TIMEOUT", "10"))
    retry_attempts: int = int(os.getenv("TICKWATCH_RETRY_ATTEMPTS", "3"))
    anomaly_z_threshold: float = float(os.getenv("TICKWATCH_ANOMALY_Z_THRESHOLD", "2"))
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("TICKWATCH_CORS_ORIGINS", "").split(",")
        if origin.strip()
    )
