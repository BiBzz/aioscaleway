# aioscaleway

Asynchronous, fully typed Python client for every
[Scaleway API](https://www.scaleway.com/en/developers/api/), built on
[httpx2](https://pypi.org/project/httpx2/), [pydantic](https://docs.pydantic.dev/)
and [whenever](https://whenever.readthedocs.io/).

```python
from aioscaleway import Scaleway

async with Scaleway() as scw:  # SCW_* from the environment
    server = await scw.compute.servers(server_id)  # load
    print(server.name, server.state)
    await server.reboot()

    async for server in scw.compute.servers.filter(name="web"):
        await server.power_off()

    async for line in scw.billing.consumptions.filter(billing_period="2026-10"):
        print(line.sku, line.value.to_decimal() if line.value else 0)
```

## Why it exists

The official SDK, `scaleway` and `scaleway-async`, sends its requests through
`requests`: the `async def` methods of `scaleway-async` block the event loop
while they wait. It also mirrors the API's own layout, one class per product
and version (`InstanceV1API`, `BillingV2Beta1API`) with flat methods.

`aioscaleway` is asynchronous down to the socket and organised around what you
manipulate rather than where Scaleway files it:

- **business areas** shared with its sibling [aioovh](https://pypi.org/project/aioovh/):
  `compute`, `storage`, `network`, `kubernetes`, `databases`, `billing`...;
- **collections** you iterate with `async for`, narrowed with `filter()`, every
  page read for you;
- **references** (`scw.compute.servers(server_id)`) that act without a
  request to read them first, and that `await` loads;
- **objects** that are references too, with typed fields;
- **one method per action**: `server.reboot()`, `server.power_off()`,
  `server.attach_volume(volume_id=volume)`;
- **no API version in any name**: the library picks the latest stable version
  of each API, else the latest preview, and says so in the docstring.

Everything is generated from the OpenAPI files Scaleway publishes, committed in
[`specs/`](specs/): 59 API versions and about 1,500 operations. Every
operation is reachable, either through the objects or through `scw.raw`, and
[`docs/coverage.md`](docs/coverage.md) says where.

## Installation

```bash
uv add aioscaleway
```

Python 3.12 or later.

## Usage

### Client

```python
scw = Scaleway(
    secret_key="...",
    default_region="fr-par",
    default_zone="fr-par-1",
    default_project_id="...",
)
nl = scw.with_options(default_zone="nl-ams-1")  # same connections, other defaults
```

Every value left out is read from the variables of the Scaleway CLI
(`SCW_SECRET_KEY`, `SCW_DEFAULT_REGION`, `SCW_DEFAULT_ZONE`,
`SCW_DEFAULT_PROJECT_ID`, `SCW_DEFAULT_ORGANIZATION_ID`, `SCW_API_URL`).
Use it as an async context manager, or call `await scw.aclose()`.

### Collections, references, objects

| You write | You get | Requests |
| --- | --- | --- |
| `scw.compute.servers` | a collection | none |
| `scw.compute.servers.filter(name="web")` | the same collection, narrowed | none |
| `async for s in scw.compute.servers` | loaded objects | one per page |
| `scw.compute.servers(server_id)` | a reference | none |
| `await scw.compute.servers(server_id)` | a loaded object | one |
| `await scw.compute.servers(server_id).reboot()` | the action's result | one |
| `await scw.compute.servers.create(name=..., commercial_type=...)` | the created object | one |

`pages()` yields each page response instead, for the totals and sums an item
does not carry (`page.total_discount_untaxed_value` of the billing
consumptions).

A loaded object is also a reference: anything that takes a reference takes an
object. It cannot load itself when printed or read, because those are
synchronous; mypy flags a field read on a bare reference. `repr()` tells which
one you hold.

Sub-resources hang off their parent:

```python
async for pool in scw.kubernetes.clusters(cluster_id).pools:
    print(pool.name, pool.size)
async for nic in scw.compute.servers(server_id).nics:
    ...
```

A resource with a zone or a region takes it as a keyword
(`scw.compute.servers(server_id, zone="nl-ams-1")`,
`servers.filter(zone="nl-ams-1")`), defaulting to the client's.

### Types

Arguments and fields are typed. Enumerations and nested models of an area live
in its `types` module:

```python
from aioscaleway.compute.types import ServerState, BootType
```

Dates are `whenever.Instant`, amounts `Money` (`.to_decimal()`).
Enumerations are open: a value Scaleway adds later is accepted instead of
failing the response.

### Errors

```python
from aioscaleway import ResourceNotFoundError, ScalewayAPIError

try:
    await scw.compute.servers(server_id)
except ResourceNotFoundError:
    ...
except ScalewayAPIError as error:
    print(error.status_code, error.type, error.message)
```

`ScalewayTransportError` reports a request that got no answer. Throttling and
transient failures are retried with [stamina](https://stamina.hynek.me/),
honouring `Retry-After`; a `POST` is only retried when Scaleway cannot have
processed it.

### The raw layer

`scw.raw` is the underlying client, for a call the objects do not cover:

```python
await scw.raw.request_json("GET", "/instance/v1/zones/fr-par-1/dashboard")
```

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/architecture.md](docs/architecture.md). The full object tree is in
[docs/objects.md](docs/objects.md).

The source lives on
[GitLab](https://gitlab.com/businessagile/libraries/aioscaleway), mirrored to
[GitHub](https://github.com/BiBzz/aioscaleway).

## License

MIT, see [LICENSE](LICENSE).
