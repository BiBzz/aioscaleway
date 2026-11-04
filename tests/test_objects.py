import re
from pathlib import Path

import pytest
from whenever import Instant

import aioscaleway
from aioscaleway import ResourceNotFoundError, Scaleway
from aioscaleway.compute import Server, ServerRef
from aioscaleway.compute.types import ServerState
from aioscaleway.kubernetes import Pool
from tests.conftest import Recorder

SERVER = {
    "id": "s1",
    "name": "web",
    "state": "running",
    "zone": "fr-par-1",
    "creation_date": "2026-10-01T08:00:00Z",
}


def test_a_reference_makes_no_request(scw: Scaleway, recorder: Recorder) -> None:
    server = scw.compute.servers("s1")

    assert isinstance(server, ServerRef)
    assert not isinstance(server, Server)
    assert "s1" in repr(server) and "not loaded" in repr(server)
    assert recorder.requests == []


async def test_awaiting_a_reference_loads_the_object(
    scw: Scaleway, recorder: Recorder
) -> None:
    recorder.reply(body={"server": SERVER})

    server = await scw.compute.servers("s1")

    assert isinstance(server, Server)
    assert isinstance(server, ServerRef)
    assert server.name == "web"
    assert server.state is ServerState.RUNNING
    assert server.creation_date == Instant.from_utc(2026, 10, 1, 8)
    assert recorder.requests[0].method == "GET"
    assert recorder.requests[0].url.path == "/instance/v1/zones/fr-par-1/servers/s1"


async def test_an_action_runs_without_loading(
    scw: Scaleway, recorder: Recorder
) -> None:
    recorder.reply(body={"task": {"id": "t1"}})

    await scw.compute.servers("s1", zone="nl-ams-1").reboot()

    (request,) = recorder.requests
    assert request.method == "POST"
    assert request.url.path == "/instance/v1/zones/nl-ams-1/servers/s1/action"
    assert recorder.body() == {"action": "reboot"}


async def test_a_loaded_object_acts_on_itself(
    scw: Scaleway, recorder: Recorder
) -> None:
    recorder.reply(body={"server": {**SERVER, "zone": "pl-waw-1"}})
    recorder.reply(body={"task": {"id": "t1"}})

    server = await scw.compute.servers("s1")
    await server.power_off()

    assert (
        recorder.requests[1].url.path == "/instance/v1/zones/pl-waw-1/servers/s1/action"
    )
    assert recorder.body() == {"action": "poweroff"}


async def test_iterating_reads_every_page_and_yields_objects(
    scw: Scaleway, recorder: Recorder
) -> None:
    recorder.reply(body={"servers": [SERVER]}, headers={"X-Total-Count": "2"})
    recorder.reply(
        body={"servers": [{**SERVER, "id": "s2"}]}, headers={"X-Total-Count": "2"}
    )

    servers = [server async for server in scw.compute.servers.filter(name="web")]

    assert [server.id for server in servers] == ["s1", "s2"]
    assert all(isinstance(server, Server) for server in servers)
    assert [r.url.params["page"] for r in recorder.requests] == ["1", "2"]
    assert recorder.requests[0].url.params["name"] == "web"


async def test_filters_add_up_and_leave_the_collection_unchanged(
    scw: Scaleway, recorder: Recorder
) -> None:
    servers = scw.compute.servers
    narrowed = servers.filter(name="web").filter(zone="nl-ams-1")
    recorder.reply(body={"servers": []}, headers={"X-Total-Count": "0"})

    assert await narrowed.all() == []
    request = recorder.requests[0]
    assert request.url.path == "/instance/v1/zones/nl-ams-1/servers"
    assert request.url.params["name"] == "web"
    assert "name" not in repr(servers)


async def test_creating_returns_a_loaded_object(
    scw: Scaleway, recorder: Recorder
) -> None:
    recorder.reply(body={"server": SERVER})

    server = await scw.compute.servers.create(name="web", commercial_type="DEV1-S")

    assert isinstance(server, Server)
    assert recorder.body()["project"] == "project-1"
    assert recorder.requests[0].url.path == "/instance/v1/zones/fr-par-1/servers"


async def test_a_sub_collection_lists_under_its_parent(
    scw: Scaleway, recorder: Recorder
) -> None:
    recorder.reply(body={"private_nics": [], "total_count": 0})

    nics = await scw.compute.servers("s1").nics.all()

    assert nics == []
    assert recorder.requests[0].url.path == (
        "/instance/v1/zones/fr-par-1/servers/s1/private_nics"
    )


async def test_a_child_with_its_own_path_belongs_to_its_parent(
    scw: Scaleway, recorder: Recorder
) -> None:
    pool = {
        "id": "p1",
        "cluster_id": "c1",
        "name": "default",
        "region": "fr-par",
        "node_type": "DEV1-M",
        "size": 1,
    }
    recorder.reply(body={"pools": [pool], "total_count": 1})
    recorder.reply(body=pool)

    listed = await scw.kubernetes.clusters("c1").pools.all()
    loaded = await scw.kubernetes.clusters("c1").pools("p1")

    assert [p.id for p in listed] == ["p1"]
    assert isinstance(loaded, Pool)
    assert recorder.requests[0].url.path == "/k8s/v1/regions/fr-par/clusters/c1/pools"
    assert recorder.requests[1].url.path == "/k8s/v1/regions/fr-par/pools/p1"


async def test_a_listing_without_items_is_still_iterable(
    scw: Scaleway, recorder: Recorder
) -> None:
    line = {"value": {"currency_code": "EUR", "units": 3}, "sku": "a"}
    recorder.reply(body={"consumptions": [line], "total_count": 2})
    recorder.reply(body={"consumptions": [{**line, "sku": "b"}], "total_count": 2})

    lines = scw.billing.consumptions.filter(billing_period="2026-10")
    skus = [consumption.sku async for consumption in lines]

    assert skus == ["a", "b"]
    assert recorder.requests[0].url.params["billing_period"] == "2026-10"


async def test_an_identifier_argument_accepts_a_reference(
    scw: Scaleway, recorder: Recorder
) -> None:
    recorder.reply(body={"server": SERVER})

    volume = scw.storage.volumes("v1")
    await scw.compute.servers("s1").attach_volume(volume_id=volume)

    assert recorder.body()["volume_id"] == "v1"


async def test_an_empty_identifier_is_refused() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        Scaleway(secret_key="k").compute.servers("")


async def test_a_missing_object_raises_the_api_error(
    scw: Scaleway, recorder: Recorder
) -> None:
    recorder.reply(404, {"type": "not_found", "message": "no server"})

    with pytest.raises(ResourceNotFoundError):
        await scw.compute.servers("missing")


def test_with_options_shares_the_connections(scw: Scaleway) -> None:
    other = scw.with_options(default_zone="nl-ams-1")

    assert other.settings.default_zone == "nl-ams-1"
    assert other.raw.http_client is scw.raw.http_client


def test_no_public_name_carries_an_api_version() -> None:
    package = Path(aioscaleway.__file__).parent
    versioned = re.compile(r"\b[A-Z]\w*V\d+(Alpha|Beta)?\d*\w*\b")
    for path in [*package.glob("*/__init__.py"), *package.glob("*/types.py")]:
        if path.parent.name.startswith("_"):
            continue
        exported = re.findall(r"^    '(\w+)',$", path.read_text(encoding="utf-8"), re.M)
        assert not [name for name in exported if versioned.search(name)], path


def test_every_operation_is_placed() -> None:
    coverage = (Path(__file__).parent.parent / "docs" / "coverage.md").read_text()
    rows = [
        line
        for line in coverage.splitlines()
        if line.startswith("| ") and "---" not in line
    ]
    placed = [
        row for row in rows[1:] if "other version" not in row and "raw only" not in row
    ]

    assert len(rows) - 1 >= 1531
    assert len(placed) > 1300


async def test_pages_keep_what_only_a_page_carries(
    scw: Scaleway, recorder: Recorder
) -> None:
    line = {"value": {"currency_code": "EUR", "units": 3}, "sku": "a"}
    page = {
        "consumptions": [line],
        "total_count": 2,
        "total_discount_untaxed_value": 1.5,
    }
    recorder.reply(body=page)
    recorder.reply(body={**page, "consumptions": [{**line, "sku": "b"}]})

    consumptions = scw.billing.consumptions.filter(
        billing_period="2026-10", page_size=1
    )
    pages = [page async for page in consumptions.pages()]

    assert [p.total_discount_untaxed_value for p in pages] == [1.5, 1.5]
    assert [r.url.params["page"] for r in recorder.requests] == ["1", "2"]
    assert recorder.requests[0].url.params["page_size"] == "1"
