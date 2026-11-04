import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import stamina
from httpx2 import MockTransport, Request, Response

from aioscaleway import Scaleway, ScalewaySettings
from aioscaleway._client import ScalewayClient

type Handler = Callable[[Request], Response]


class Recorder:
    """A transport that answers from a queue of handlers and keeps every request."""

    def __init__(self) -> None:
        self.requests: list[Request] = []
        self.handlers: list[Handler] = []

    def reply(
        self, status: int = 200, body: Any = None, headers: dict[str, str] | None = None
    ) -> None:
        def handler(request: Request) -> Response:
            return Response(status, json=body, headers=headers)

        self.handlers.append(handler)

    def push(self, handler: Handler) -> None:
        self.handlers.append(handler)

    def __call__(self, request: Request) -> Response:
        self.requests.append(request)
        if not self.handlers:
            raise AssertionError(f"unexpected request {request.method} {request.url}")
        return self.handlers.pop(0)(request)

    def body(self, index: int = -1) -> Any:
        return json.loads(self.requests[index].content)


@pytest.fixture(autouse=True)
def no_retry_wait() -> Iterator[None]:
    stamina.set_testing(True, attempts=3)
    yield
    stamina.set_testing(False)


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


SETTINGS = ScalewaySettings(
    secret_key="secret",
    default_region="fr-par",
    default_zone="fr-par-1",
    default_project_id="project-1",
    default_organization_id="organization-1",
)


@pytest.fixture
def client(recorder: Recorder) -> ScalewayClient:
    return ScalewayClient(SETTINGS, transport=MockTransport(recorder))


@pytest.fixture
def scw(recorder: Recorder) -> Scaleway:
    return Scaleway(settings=SETTINGS, transport=MockTransport(recorder))
