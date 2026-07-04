"""Source-specific exceptions."""

from core.exceptions import ExternalServiceException, UnauthorizedException


class SourceFetchError(ExternalServiceException):
    """Raised when a document source fails to fetch content."""

    def __init__(self, message: str = "Failed to fetch document from source"):
        super().__init__(message=message)


class SourceAuthError(UnauthorizedException):
    """Raised when source authentication fails (expired token, etc.)."""

    def __init__(self, message: str = "Source authentication failed"):
        super().__init__(message=message)
