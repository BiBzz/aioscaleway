from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import date, datetime
from enum import Enum
from http import HTTPStatus
from types import TracebackType
from typing import Any, Self
from urllib.parse import quote

from httpx2 import (
    AsyncBaseTransport,
    AsyncClient,
    ConnectError,
    ConnectTimeout,
    Response,
    TransportError,
)
from pydantic import BaseModel
from stamina import retry_context

from aioscaleway._errors import (
    ScalewayAPIError,
    ScalewayConfigurationError,
    ScalewayTransportError,
    api_error,
)
from aioscaleway._settings import ScalewaySettings

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
RETRYABLE_STATUSES = frozenset(
    {
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    }
)
NEVER_PROCESSED_STATUSES = frozenset(
    {HTTPStatus.TOO_MANY_REQUESTS, HTTPStatus.SERVICE_UNAVAILABLE}
)
type QueryValue = str | int | float | bool | Enum | datetime | date | None
type Query = Mapping[str, QueryValue | list[Any]]
type QueryPairs = list[tuple[str, str | int | float | bool | None]]


def retry_decision(method: str, error: Exception) -> bool | float:
    """Tell stamina whether to retry, waiting Retry-After seconds when given."""
    if isinstance(error, ScalewayAPIError):
        if error.status_code not in RETRYABLE_STATUSES:
            return False
        if method not in IDEMPOTENT_METHODS and (
            error.status_code not in NEVER_PROCESSED_STATUSES
        ):
            return False
        retry_after = error.headers.get("retry-after", "")
        return float(retry_after) if retry_after.isdigit() else True
    if isinstance(error, ScalewayTransportError):
        return method in IDEMPOTENT_METHODS or isinstance(
            error.__cause__, ConnectError | ConnectTimeout
        )
    return False


def query_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def encode_query(params: Query | None) -> QueryPairs:
    pairs: QueryPairs = []
    for name, value in (params or {}).items():
        if value is None:
            continue
        values = value if isinstance(value, list) else [value]
        pairs.extend((name, query_value(item)) for item in values if item is not None)
    return pairs


def encode_body(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_unset=True)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            key: encode_body(item) for key, item in value.items() if item is not None
        }
    if isinstance(value, list | tuple):
        return [encode_body(item) for item in value]
    return value


class ScalewayClient:
    """Authenticated, retrying HTTP access to the Scaleway API.

    Every generated API class takes this client, as the official SDK does:
    `BillingV2Beta1API(client)`.
    """

    def __init__(
        self,
        settings: ScalewaySettings | None = None,
        *,
        transport: AsyncBaseTransport | None = None,
        http_client: AsyncClient | None = None,
    ) -> None:
        self.settings = ScalewaySettings() if settings is None else settings
        self._owns_http_client = http_client is None
        self._http = http_client or AsyncClient(
            base_url=self.settings.api_url,
            transport=transport,
            timeout=self.settings.timeout,
        )

    @classmethod
    def from_values(cls, **values: Any) -> Self:
        return cls(ScalewaySettings(**values))

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http.aclose()

    def region(self, region: str | None) -> str:
        value = region or self.settings.default_region
        if not value:
            raise ScalewayConfigurationError(
                "No region given and no default_region configured (SCW_DEFAULT_REGION)."
            )
        return value

    def zone(self, zone: str | None) -> str:
        value = zone or self.settings.default_zone
        if not value:
            raise ScalewayConfigurationError(
                "No zone given and no default_zone configured (SCW_DEFAULT_ZONE)."
            )
        return value

    def project_id(self, project_id: str | None) -> str | None:
        return project_id or self.settings.default_project_id

    def organization_id(self, organization_id: str | None) -> str | None:
        return organization_id or self.settings.default_organization_id

    def owner(
        self,
        *,
        project_id: str | None,
        organization_id: str | None,
        keys: tuple[str, str] = ("project_id", "organization_id"),
    ) -> dict[str, str]:
        """Pick the project or the organization a resource belongs to."""
        project_key, organization_key = keys
        if project_id:
            return {project_key: project_id}
        if organization_id:
            return {organization_key: organization_id}
        if self.settings.default_project_id:
            return {project_key: self.settings.default_project_id}
        if self.settings.default_organization_id:
            return {organization_key: self.settings.default_organization_id}
        return {}

    @staticmethod
    def path(template: str, **values: Any) -> str:
        if any(value is None or value == "" for value in values.values()):
            missing = [name for name, value in values.items() if value in (None, "")]
            raise ScalewayConfigurationError(
                f"Empty path parameter: {', '.join(missing)}."
            )
        return template.format(
            **{
                name: quote(query_value(value), safe="")
                for name, value in values.items()
            }
        )

    def _headers(self, extra: Mapping[str, str] | None) -> dict[str, str]:
        headers = {"User-Agent": self.settings.user_agent}
        if self.settings.secret_key is not None:
            headers["X-Auth-Token"] = self.settings.secret_key.get_secret_value()
        headers.update(extra or {})
        return headers

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Query | None = None,
        body: Any = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        """Send one request, retried on throttling and transient failures."""
        method = method.upper()
        query = encode_query(params)
        json_body = None if body is None else encode_body(body)
        request_headers = self._headers(headers)
        async for attempt in retry_context(
            on=lambda error: retry_decision(method, error),
            attempts=self.settings.retry_attempts,
            timeout=self.settings.retry_timeout,
            wait_initial=self.settings.retry_wait_initial,
            wait_max=self.settings.retry_wait_max,
        ):
            with attempt:
                return await self._send(
                    method, path, query, json_body, content, request_headers
                )
        raise AssertionError("unreachable: stamina either returns or raises")

    async def _send(
        self,
        method: str,
        path: str,
        query: QueryPairs,
        json_body: Any,
        content: bytes | None,
        headers: dict[str, str],
    ) -> Response:
        try:
            response = await self._http.request(
                method,
                path,
                params=query,
                json=json_body,
                content=content,
                headers=headers,
            )
        except TransportError as error:
            raise ScalewayTransportError(method, path, repr(error)) from error
        if response.is_error:
            try:
                error_body: Any = response.json()
            except ValueError:
                error_body = response.text
            raise api_error(
                method,
                str(response.url),
                response.status_code,
                error_body,
                dict(response.headers),
            )
        return response

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Query | None = None,
        body: Any = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = await self.request(
            method, path, params=params, body=body, content=content, headers=headers
        )
        if response.status_code == HTTPStatus.NO_CONTENT or not response.content:
            return None
        return response.json()


async def paginate[Page, Item](
    fetch: Callable[[int], Awaitable[Page]],
    items: Callable[[Page], list[Item]],
    total: Callable[[Page], int | None],
) -> AsyncIterator[Item]:
    """Walk the `page` / `page_size` pagination until `total_count` items are read."""
    page_number = 1
    seen = 0
    while True:
        page = await fetch(page_number)
        batch = items(page)
        for item in batch:
            yield item
        seen += len(batch)
        expected = total(page)
        if not batch or (expected is not None and seen >= expected):
            return
        page_number += 1
