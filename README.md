# aioscaleway

Asynchronous, fully typed Python client for every
[Scaleway API](https://www.scaleway.com/en/developers/api/), built on
[httpx2](https://pypi.org/project/httpx2/) and
[pydantic](https://docs.pydantic.dev/).

The modules and class names follow the official
[`scaleway`](https://pypi.org/project/scaleway/) SDK, so moving code over is
mostly a matter of adding `await`:

```python
from scaleway.billing.v2beta1 import BillingV2Beta1API  # official, blocking
from aioscaleway.billing.v2beta1 import BillingV2Beta1API  # this package
```

## Why it exists

The official SDK comes in two flavours, `scaleway` and `scaleway-async`, and
both send their requests through `requests`. The `async def` methods of
`scaleway-async` call it directly, so every request blocks the event loop
while it waits for Scaleway. `aioscaleway` is asynchronous down to the socket:

- one `httpx2.AsyncClient` per `ScalewayClient`, connections reused;
- every request and response is a pydantic model, checked by `mypy --strict`;
- throttling (`429`) and transient failures (`502`, `503`, `504`, broken
  connections) are retried with [stamina](https://stamina.hynek.me/), honouring
  `Retry-After`, and a `POST` is only retried when Scaleway cannot have
  processed it;
- every paginated listing has an `_iter` and an `_all` variant;
- API errors are typed (`ResourceNotFoundError`, `QuotasExceededError`, and
  so on) and keep Scaleway's message.

The code is generated from the OpenAPI files Scaleway publishes, which are
committed in [`specs/`](specs/): 59 API versions and around 1,500 operations,
not only the popular ones.

## Installation

```bash
uv add aioscaleway
```

or:

```bash
pip install aioscaleway
```

Python 3.12 or later.

## Usage

```python
import asyncio

from aioscaleway import ScalewayClient, ScalewaySettings
from aioscaleway.billing.v2beta1 import BillingV2Beta1API
from aioscaleway.instance.v1 import InstanceV1API


async def main() -> None:
    settings = ScalewaySettings(
        secret_key="...",
        default_region="fr-par",
        default_zone="fr-par-1",
        default_project_id="...",
    )
    async with ScalewayClient(settings) as client:
        billing = BillingV2Beta1API(client)
        for line in await billing.list_consumptions_all(billing_period="2026-10"):
            print(line.sku, line.value.to_decimal() if line.value else 0)

        instance = InstanceV1API(client)
        async for server in instance.list_servers_iter():
            print(server.name, server.state)


asyncio.run(main())
```

### Configuration

`ScalewaySettings` is a `pydantic-settings` object. Left empty, it reads the
same environment variables as the Scaleway CLI and the official SDK:

| Variable                      | Setting                   |
| ----------------------------- | ------------------------- |
| `SCW_SECRET_KEY`              | `secret_key`              |
| `SCW_ACCESS_KEY`              | `access_key`              |
| `SCW_API_URL`                 | `api_url`                 |
| `SCW_DEFAULT_REGION`          | `default_region`          |
| `SCW_DEFAULT_ZONE`            | `default_zone`            |
| `SCW_DEFAULT_PROJECT_ID`      | `default_project_id`      |
| `SCW_DEFAULT_ORGANIZATION_ID` | `default_organization_id` |

```python
client = ScalewayClient()  # reads SCW_* from the environment
```

Timeouts and the retry policy are settings too: `timeout`, `retry_attempts`,
`retry_timeout`, `retry_wait_initial` and `retry_wait_max`.

### Regions, zones and owners

A method whose path contains a region or a zone takes an optional `region` or
`zone` argument, and falls back to the configured default. Creating a
resource without a `project_id` uses `default_project_id`, as the official SDK
does; when an operation accepts either a project or an organization, only one
of them is sent.

### Pagination

Every listing that pages with `page` and `page_size` (or `per_page`) gets two
helpers next to the plain method:

```python
async for project in api.list_projects_iter():
    ...  # page after page
projects = await api.list_projects_all()  # every page, as a list
```

### Errors

```python
from aioscaleway import ResourceNotFoundError, ScalewayAPIError

try:
    await instance.get_server(server_id="...")
except ResourceNotFoundError:
    ...
except ScalewayAPIError as error:
    print(error.status_code, error.type, error.message)
```

`ScalewayTransportError` reports a request that never got an answer, and
`ScalewayConfigurationError` a missing region, zone or path parameter.

### Values added after generation

Enumerations are open: a status Scaleway adds later is accepted and keeps its
value (`ServerState("hibernating")`), instead of failing the whole response.
Fields unknown to the models are kept in `model_extra`.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). The design choices are in
[docs/architecture.md](docs/architecture.md).

The source lives on
[GitLab](https://gitlab.com/businessagile/libraries/aioscaleway), mirrored to
[GitHub](https://github.com/BiBzz/aioscaleway). A sibling package covers
OVHcloud: [aioovh](https://pypi.org/project/aioovh/).

## License

MIT, see [LICENSE](LICENSE).
