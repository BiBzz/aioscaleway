<style>
.md-content .md-typeset h1 { display: none; }
</style>

# aioscaleway

<p align="center">
  <a href="https://aioscaleway.businessagile.eu"><img src="img/logo.svg" alt="aioscaleway" width="460"></a>
</p>
<p align="center">
    <em>aioscaleway, every Scaleway API in Python, fully async and strongly typed.</em>
</p>
<p align="center">
<a href="https://gitlab.com/businessagile/libraries/aioscaleway/-/blob/development/LICENSE" target="_blank"><img src="img/badges/license.svg" alt="License: MIT"></a>
<img src="img/badges/status.svg" alt="Status: beta">
<img src="img/badges/python.svg" alt="Python 3.12+">
</p>

---

**Documentation**: <a href="https://aioscaleway.businessagile.eu" target="_blank">https://aioscaleway.businessagile.eu</a>

**Source Code**: <a href="https://gitlab.com/businessagile/libraries/aioscaleway" target="_blank">https://gitlab.com/businessagile/libraries/aioscaleway</a>

---

aioscaleway is a client for the **Scaleway APIs**, organised around what you manipulate (servers, volumes, clusters, invoices) rather than where Scaleway files it. It is **async from end to end** and **strongly typed**, and covers **every published API**, not only the popular ones.

**aioscaleway** is based on Python type annotations, and powered by <a href="https://docs.pydantic.dev" target="_blank">Pydantic</a>, <a href="https://pypi.org/project/httpx2/" target="_blank">httpx2</a>, <a href="https://whenever.readthedocs.io" target="_blank">whenever</a> and <a href="https://stamina.hynek.me" target="_blank">stamina</a>.

The key features are:

* **Async first**: one HTTP client per `Scaleway` object, every call awaited. The official `scaleway-async` package calls `requests` inside its `async def` methods and blocks the event loop.
* **Business areas**: `compute`, `storage`, `network`, `kubernetes`, `databases`, `billing`... the same areas as its sibling <a href="https://aioovh.businessagile.eu" target="_blank">aioovh</a>.
* **References and objects**: `scw.compute.servers(server_id)` acts without reading the server first, `await` loads it, and a loaded server is still a reference.
* **Collections**: `async for` reads every page, `filter()` narrows, `pages()` gives the page totals.
* **One method per action**: `server.reboot()`, `server.power_off()`, `server.attach_volume(volume_id=volume)`.
* **No API version in any name**: the latest stable version of each API, else its latest preview, chosen for you.
* **Complete**: generated from the 91 OpenAPI files Scaleway publishes, 59 API versions and about 1,500 operations, each reachable.

## Requirements

A recent and currently supported <a href="https://www.python.org/downloads/" target="_blank">version of Python</a>: 3.12 or later.

A Scaleway API key, given as an argument or read from the `SCW_*` variables of the Scaleway CLI.

## Installation

```console
$ pip install aioscaleway
---> 100%
Successfully installed aioscaleway httpx2 pydantic pydantic-settings stamina whenever
```

## Example

### Connect

```python
from aioscaleway import Scaleway

scw = Scaleway(
    secret_key="...",
    default_region="fr-par",
    default_zone="fr-par-1",
    default_project_id="...",
)
```

Every value left out is read from `SCW_SECRET_KEY`, `SCW_DEFAULT_REGION`, `SCW_DEFAULT_ZONE`, `SCW_DEFAULT_PROJECT_ID` and the other variables of the Scaleway CLI.

### Load, act, iterate

```python hl_lines="2  4  6  8"
async with scw:
    server = await scw.compute.servers(server_id)
    print(server.name, server.state)
    await server.reboot()

    await scw.compute.servers(other_id).power_off()

    async for server in scw.compute.servers.filter(name="web"):
        print(server.id, server.creation_date)
```

`scw.compute.servers(server_id)` is a reference: it makes no request. `await` loads the server, an action runs directly on the reference, and iterating the collection reads every page.

### Sub-resources

```python
async for pool in scw.kubernetes.clusters(cluster_id).pools:
    print(pool.name, pool.size)
```

A pool belongs to its cluster, even though Scaleway serves it at `/pools/{pool_id}`.

### Billing, with totals

```python
consumptions = scw.billing.consumptions.filter(billing_period="2026-10")
async for page in consumptions.pages():
    for line in page.consumptions:
        print(line.sku, line.value.to_decimal() if line.value else 0)
    print("discount", page.total_discount_untaxed_value)
```

### Editor support everywhere

Arguments, fields and results are typed, and checked with `mypy --strict`. Dates are `whenever.Instant`, amounts `Money` with `.to_decimal()`, enumerations are open so that a value Scaleway adds later does not break your code.

## License

This project is licensed under the terms of the [MIT license](https://gitlab.com/businessagile/libraries/aioscaleway/-/blob/development/LICENSE).
