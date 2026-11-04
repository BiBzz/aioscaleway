from http import HTTPStatus
from typing import Any


class ScalewayError(Exception):
    """Base class of every error raised by aioscaleway."""


class ScalewayConfigurationError(ScalewayError):
    """A value the request needs is neither given nor configured."""


class ScalewayTransportError(ScalewayError):
    """The API could not be reached, or the connection broke."""

    def __init__(self, method: str, url: str, reason: str) -> None:
        super().__init__(f"{method} {url} failed: {reason}")
        self.method = method
        self.url = url


class ScalewayAPIError(ScalewayError):
    """The API answered with an error status."""

    def __init__(
        self,
        method: str,
        url: str,
        status_code: int,
        body: Any,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.method = method
        self.url = url
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}
        details = body if isinstance(body, dict) else {}
        self.type: str | None = details.get("type")
        self.message: str = str(details.get("message") or body or "")
        self.details: Any = details.get("details")
        super().__init__(f"{method} {url} answered {status_code}: {self.message}")


class InvalidArgumentsError(ScalewayAPIError):
    pass


class DeniedAuthenticationError(ScalewayAPIError):
    pass


class PermissionsDeniedError(ScalewayAPIError):
    pass


class QuotasExceededError(ScalewayAPIError):
    pass


class ResourceNotFoundError(ScalewayAPIError):
    pass


class ConflictError(ScalewayAPIError):
    pass


class TransientStateError(ConflictError):
    pass


class PreconditionFailedError(ScalewayAPIError):
    pass


class ResourceExpiredError(ScalewayAPIError):
    pass


class OutOfStockError(ScalewayAPIError):
    pass


class TooManyRequestsError(ScalewayAPIError):
    pass


class ServerError(ScalewayAPIError):
    pass


ERRORS_BY_TYPE: dict[str, type[ScalewayAPIError]] = {
    "invalid_arguments": InvalidArgumentsError,
    "denied_authentication": DeniedAuthenticationError,
    "permissions_denied": PermissionsDeniedError,
    "quotas_exceeded": QuotasExceededError,
    "not_found": ResourceNotFoundError,
    "unknown_resource": ResourceNotFoundError,
    "conflict": ConflictError,
    "transient_state": TransientStateError,
    "precondition_failed": PreconditionFailedError,
    "resource_expired": ResourceExpiredError,
    "out_of_stock": OutOfStockError,
}

ERRORS_BY_STATUS: dict[int, type[ScalewayAPIError]] = {
    HTTPStatus.BAD_REQUEST: InvalidArgumentsError,
    HTTPStatus.UNAUTHORIZED: DeniedAuthenticationError,
    HTTPStatus.FORBIDDEN: PermissionsDeniedError,
    HTTPStatus.NOT_FOUND: ResourceNotFoundError,
    HTTPStatus.CONFLICT: ConflictError,
    HTTPStatus.GONE: ResourceExpiredError,
    HTTPStatus.PRECONDITION_FAILED: PreconditionFailedError,
    HTTPStatus.TOO_MANY_REQUESTS: TooManyRequestsError,
}


def api_error(
    method: str,
    url: str,
    status_code: int,
    body: Any,
    headers: dict[str, str] | None = None,
) -> ScalewayAPIError:
    error_type = body.get("type") if isinstance(body, dict) else None
    error_class = ERRORS_BY_TYPE.get(str(error_type)) or ERRORS_BY_STATUS.get(
        status_code,
        ServerError
        if status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
        else ScalewayAPIError,
    )
    return error_class(method, url, status_code, body, headers)
