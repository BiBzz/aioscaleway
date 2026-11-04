from types import TracebackType
from typing import Any, Self

from httpx2 import AsyncBaseTransport, AsyncClient
from pydantic import SecretStr

from aioscaleway._client import ScalewayClient
from aioscaleway._namespaces import Namespaces
from aioscaleway._objects import Session
from aioscaleway._settings import ScalewaySettings


class Scaleway(Namespaces):
    """The Scaleway API, organised by business area: `scw.compute.servers`.

    Values left out are read from the `SCW_*` environment variables.
    """

    def __init__(
        self,
        *,
        secret_key: str | None = None,
        access_key: str | None = None,
        api_url: str | None = None,
        default_region: str | None = None,
        default_zone: str | None = None,
        default_project_id: str | None = None,
        default_organization_id: str | None = None,
        settings: ScalewaySettings | None = None,
        http_client: AsyncClient | None = None,
        transport: AsyncBaseTransport | None = None,
    ) -> None:
        changes: dict[str, Any] = {
            "secret_key": None if secret_key is None else SecretStr(secret_key),
            "access_key": access_key,
            "api_url": api_url,
            "default_region": default_region,
            "default_zone": default_zone,
            "default_project_id": default_project_id,
            "default_organization_id": default_organization_id,
        }
        base = ScalewaySettings() if settings is None else settings
        self.settings = base.model_copy(
            update={name: value for name, value in changes.items() if value is not None}
        )
        self.raw = ScalewayClient(
            self.settings, http_client=http_client, transport=transport
        )
        self._session = Session(self.raw)

    def with_options(self, **changes: Any) -> Self:
        """A client sharing this one's connections, with other settings."""
        settings = self.settings.model_copy(update=changes)
        return type(self)(settings=settings, http_client=self.raw.http_client)

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
        await self.raw.aclose()
