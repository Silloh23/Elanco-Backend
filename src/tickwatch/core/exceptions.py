"""Application-level exceptions mapped to stable API errors."""


class TickWatchError(Exception):
    """Base class for expected application errors."""


class UpstreamAPIError(TickWatchError):
    """Raised when the source API fails after bounded retries."""


class ValidationFailure(TickWatchError):
    """Raised when a source record cannot be safely normalized."""


class NotFound(TickWatchError):
    """Raised when a requested local record does not exist."""
