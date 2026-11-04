from decimal import Decimal
from http import HTTPStatus

import pytest
from httpx2 import ConnectError, MockTransport, ReadTimeout, Request, Response

from aioscaleway import (
    InvalidArgumentsError,
    Money,
    QuotasExceededError,
    ResourceNotFoundError,
    ScalewayClient,
    ScalewayConfigurationError,
    ScalewaySettings,
    ScalewayTransportError,
    ServerError,
    TooManyRequestsError,
)
from aioscaleway.instance.v1 import Arch
from tests.conftest import Recorder


async def test_requests_carry_the_secret_key(
    client: ScalewayClient, recorder: Recorder
) -> None:
    recorder.reply(body={})

    await client.request("GET", "/account/v3/projects")

    assert recorder.requests[0].headers["X-Auth-Token"] == "secret"
    assert recorder.requests[0].headers["User-Agent"] == "aioscaleway"


async def test_query_values_are_encoded_and_none_dropped(
    client: ScalewayClient, recorder: Recorder
) -> None:
    recorder.reply(body={})

    await client.request(
        "GET",
        "/x",
        params={"flag": True, "arch": Arch.ARM64, "tags": ["a", "b"], "name": None},
    )

    assert recorder.requests[0].url.query == b"flag=true&arch=arm64&tags=a&tags=b"


def test_path_parameters_are_quoted() -> None:
    assert ScalewayClient.path("/a/{id}", id="x/y z") == "/a/x%2Fy%20z"


def test_an_empty_path_parameter_is_refused() -> None:
    with pytest.raises(ScalewayConfigurationError):
        ScalewayClient.path("/a/{id}", id="")


def test_region_and_zone_fall_back_to_the_defaults(client: ScalewayClient) -> None:
    assert client.region(None) == "fr-par"
    assert client.region("nl-ams") == "nl-ams"
    assert client.zone(None) == "fr-par-1"


def test_a_missing_region_is_a_configuration_error() -> None:
    client = ScalewayClient(ScalewaySettings(secret_key="secret"))

    with pytest.raises(ScalewayConfigurationError, match="SCW_DEFAULT_REGION"):
        client.region(None)


def test_settings_read_the_official_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCW_SECRET_KEY", "from-env")
    monkeypatch.setenv("SCW_DEFAULT_REGION", "pl-waw")

    settings = ScalewaySettings()

    assert settings.secret_key is not None
    assert settings.secret_key.get_secret_value() == "from-env"
    assert settings.default_region == "pl-waw"


def test_the_owner_prefers_the_given_project(client: ScalewayClient) -> None:
    assert client.owner(project_id=None, organization_id="org") == {
        "organization_id": "org"
    }
    assert client.owner(project_id=None, organization_id=None) == {
        "project_id": "project-1"
    }
    assert client.owner(
        project_id=None, organization_id=None, keys=("project", "organization")
    ) == {"project": "project-1"}


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (
            HTTPStatus.NOT_FOUND,
            {"type": "not_found", "message": "gone"},
            ResourceNotFoundError,
        ),
        (HTTPStatus.BAD_REQUEST, {"message": "bad"}, InvalidArgumentsError),
        (HTTPStatus.FORBIDDEN, {"type": "quotas_exceeded"}, QuotasExceededError),
        (HTTPStatus.INTERNAL_SERVER_ERROR, "oops", ServerError),
    ],
)
async def test_errors_are_typed(
    client: ScalewayClient,
    recorder: Recorder,
    status: HTTPStatus,
    body: object,
    error: type[Exception],
) -> None:
    recorder.reply(status, body)

    with pytest.raises(error):
        await client.request("GET", "/x")


async def test_the_error_keeps_the_api_message(
    client: ScalewayClient, recorder: Recorder
) -> None:
    recorder.reply(HTTPStatus.NOT_FOUND, {"type": "not_found", "message": "no server"})

    with pytest.raises(ResourceNotFoundError) as caught:
        await client.request("GET", "/x")

    assert caught.value.message == "no server"
    assert caught.value.status_code == HTTPStatus.NOT_FOUND


async def test_throttling_is_retried(
    client: ScalewayClient, recorder: Recorder
) -> None:
    recorder.reply(HTTPStatus.TOO_MANY_REQUESTS, {}, headers={"Retry-After": "1"})
    recorder.reply(body={"ok": True})

    assert await client.request_json("POST", "/x", body={}) == {"ok": True}
    assert len(recorder.requests) == 2


async def test_retries_stop_after_the_last_attempt(
    client: ScalewayClient, recorder: Recorder
) -> None:
    for _ in range(3):
        recorder.reply(HTTPStatus.TOO_MANY_REQUESTS, {})

    with pytest.raises(TooManyRequestsError):
        await client.request("GET", "/x")
    assert len(recorder.requests) == 3


async def test_a_post_is_not_retried_on_a_bad_gateway(
    client: ScalewayClient, recorder: Recorder
) -> None:
    recorder.reply(HTTPStatus.BAD_GATEWAY, {})

    with pytest.raises(ServerError):
        await client.request("POST", "/x", body={})
    assert len(recorder.requests) == 1


async def test_a_get_is_retried_on_a_bad_gateway(
    client: ScalewayClient, recorder: Recorder
) -> None:
    recorder.reply(HTTPStatus.BAD_GATEWAY, {})
    recorder.reply(body={})

    await client.request("GET", "/x")

    assert len(recorder.requests) == 2


async def test_transport_errors_are_wrapped_and_retried_when_safe(
    recorder: Recorder,
) -> None:
    def broken(request: Request) -> Response:
        raise ReadTimeout("slow", request=request)

    recorder.push(broken)
    recorder.push(broken)
    recorder.push(broken)
    client = ScalewayClient(ScalewaySettings(), transport=MockTransport(recorder))

    with pytest.raises(ScalewayTransportError):
        await client.request("GET", "/x")
    assert len(recorder.requests) == 3


async def test_a_post_is_retried_when_the_connection_never_opened(
    recorder: Recorder,
) -> None:
    def refused(request: Request) -> Response:
        raise ConnectError("refused", request=request)

    recorder.push(refused)
    recorder.reply(body={})
    client = ScalewayClient(ScalewaySettings(), transport=MockTransport(recorder))

    await client.request("POST", "/x", body={})

    assert len(recorder.requests) == 2


async def test_no_content_decodes_to_none(
    client: ScalewayClient, recorder: Recorder
) -> None:
    recorder.push(lambda request: Response(HTTPStatus.NO_CONTENT))

    assert await client.request_json("DELETE", "/x") is None


def test_unknown_enum_values_are_accepted() -> None:
    arch = Arch("riscv64")

    assert arch == "riscv64"
    assert arch.name == "RISCV64"
    assert Arch("arm64") is Arch.ARM64


def test_money_converts_to_decimal() -> None:
    money = Money(currency_code="EUR", units=12, nanos=340_000_000)

    assert money.to_decimal() == Decimal("12.34")
