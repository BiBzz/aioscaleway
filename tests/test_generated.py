import importlib
import inspect
import pkgutil
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import BaseModel

import aioscaleway
from aioscaleway import ScalewayClient
from aioscaleway.billing.v2beta1 import (
    BillingV2Beta1API,
    ListConsumptionsRequestOrderBy,
    ListConsumptionsResponse,
)
from aioscaleway.instance.v1 import InstanceV1API, ServerState
from aioscaleway.k8s.v1 import K8SV1API
from tests.conftest import Recorder

GENERATED_MODULES = sorted(
    info.name
    for info in pkgutil.walk_packages(aioscaleway.__path__, "aioscaleway.")
    if info.name.count(".") == 3 and info.name.endswith(".models")
)


def test_every_product_is_generated() -> None:
    assert len(GENERATED_MODULES) >= 59


@pytest.mark.parametrize("module_name", GENERATED_MODULES)
def test_every_model_resolves_its_references(module_name: str) -> None:
    module = importlib.import_module(module_name)
    models = [
        value
        for value in vars(module).values()
        if inspect.isclass(value)
        and issubclass(value, BaseModel)
        and value.__module__ == module_name
    ]

    for model in models:
        assert model.model_rebuild(raise_errors=True) in (None, True)


def consumption(sku: str, units: int) -> dict[str, object]:
    return {
        "value": {"currency_code": "EUR", "units": units, "nanos": 500_000_000},
        "product_name": "Instances",
        "category_name": "Compute",
        "sku": sku,
        "project_id": "p",
        "resource_name": "r",
        "unit": "hour",
        "billed_quantity": "1",
        "consumer_id": "c",
    }


async def test_a_call_maps_arguments_and_parses_the_response(
    client: ScalewayClient, recorder: Recorder
) -> None:
    recorder.reply(
        body={
            "consumptions": [consumption("a", 1)],
            "total_count": 1,
            "total_discount_untaxed_value": 0.0,
            "updated_at": "2026-11-01T00:00:00Z",
        }
    )

    result = await BillingV2Beta1API(client).list_consumptions(
        organization_id="org",
        billing_period="2026-10",
        order_by=ListConsumptionsRequestOrderBy.UPDATED_AT_DESC,
    )

    assert isinstance(result, ListConsumptionsResponse)
    assert result.updated_at == datetime(2026, 11, 1, tzinfo=UTC)
    assert result.consumptions[0].value is not None
    assert result.consumptions[0].value.to_decimal() == Decimal("1.5")
    query = recorder.requests[0].url.params
    assert recorder.requests[0].url.path == "/billing/v2beta1/consumptions"
    assert query["billing_period"] == "2026-10"
    assert query["order_by"] == "updated_at_desc"
    assert "project_id" not in query


async def test_pagination_reads_every_page(
    client: ScalewayClient, recorder: Recorder
) -> None:
    recorder.reply(body={"consumptions": [consumption("a", 1)], "total_count": 2})
    recorder.reply(body={"consumptions": [consumption("b", 2)], "total_count": 2})

    lines = await BillingV2Beta1API(client).list_consumptions_all(
        organization_id="org", page_size=1
    )

    assert [line.sku for line in lines] == ["a", "b"]
    assert [request.url.params["page"] for request in recorder.requests] == ["1", "2"]


async def test_pagination_reads_the_total_from_the_header(
    client: ScalewayClient, recorder: Recorder
) -> None:
    server = {"id": "s1", "name": "web", "state": "running"}
    recorder.reply(body={"servers": [server]}, headers={"X-Total-Count": "2"})
    recorder.reply(
        body={"servers": [{**server, "id": "s2"}]}, headers={"X-Total-Count": "2"}
    )

    servers = await InstanceV1API(client).list_servers_all(per_page=1)

    assert [server.id for server in servers] == ["s1", "s2"]
    assert servers[0].state is ServerState.RUNNING
    assert recorder.requests[0].url.path == "/instance/v1/zones/fr-par-1/servers"


async def test_a_creation_defaults_to_the_configured_project(
    client: ScalewayClient, recorder: Recorder
) -> None:
    recorder.reply(body={"server": {"id": "s1", "name": "web"}})

    await InstanceV1API(client).create_server(
        name="web", commercial_type="DEV1-S", zone="nl-ams-1"
    )

    body = recorder.body()
    assert body["project"] == "project-1"
    assert "organization" not in body
    assert recorder.requests[0].url.path == "/instance/v1/zones/nl-ams-1/servers"


async def test_the_regional_path_uses_the_default_region(
    client: ScalewayClient, recorder: Recorder
) -> None:
    recorder.reply(body={"clusters": [], "total_count": 0})

    await K8SV1API(client).list_clusters()

    assert recorder.requests[0].url.path == "/k8s/v1/regions/fr-par/clusters"
