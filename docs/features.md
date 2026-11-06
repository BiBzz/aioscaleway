# Features

## Async down to the socket

Scaleway's official SDK comes in two packages, `scaleway` and `scaleway-async`, and both send their requests with `requests`. The `async def` methods of `scaleway-async` call it directly, so each request blocks the event loop of a FastAPI application or a task worker while it waits for Scaleway.

aioscaleway keeps one `httpx2.AsyncClient` per `Scaleway` object, reuses its connections, and awaits every request. A hundred concurrent calls are a hundred coroutines, not a hundred threads.

## Business objects, not URLs

Scaleway's APIs are organised by product and version: `/instance/v1/zones/{zone}/servers`, `/k8s/v1/regions/{region}/pools/{pool_id}`. The official SDK mirrors them, one class per product and version (`InstanceV1API`, `BillingV2Beta1API`).

aioscaleway exposes what you manipulate instead:

| You write | You get | Requests |
| --- | --- | --- |
| `scw.compute.servers` | a collection | none |
| `scw.compute.servers.filter(name="web")` | the same collection, narrowed | none |
| `async for s in scw.compute.servers` | loaded objects | one per page |
| `scw.compute.servers(server_id)` | a reference | none |
| `await scw.compute.servers(server_id)` | a loaded object | one |
| `await scw.compute.servers(server_id).reboot()` | the action's result | one |
| `await scw.compute.servers.create(...)` | the created object | one |

A loaded object is a reference too: anything that takes a reference takes an object. A reference does not load itself when printed or read, because those are synchronous; mypy flags a field read on a bare reference, and `repr()` tells which one you hold.

## Business areas

| Area | What it holds |
| --- | --- |
| `compute` | Instances, Elastic Metal, Apple silicon, Dedibox, autoscaling, images |
| `storage` | Block Storage volumes and snapshots, File Storage |
| `network` | VPC, private networks, gateways, load balancers, IPs, InterLink, VPN, Edge Services |
| `kubernetes` | clusters, pools, nodes, container registries |
| `serverless` | containers, functions, jobs |
| `databases` | PostgreSQL and MySQL, MongoDB, Redis, ClickHouse, OpenSearch, Serverless SQL |
| `analytics`, `messaging`, `ai`, `iot` | Spark, Kafka and NATS, inference and quantum, IoT Hub |
| `email`, `domains`, `web_hosting` | mailboxes and transactional email, domains and DNS, web hosting |
| `observability`, `iam`, `account` | Cockpit and Audit Trail, IAM and secrets, projects and organization |
| `billing`, `orders` | consumption, invoices, discounts, the product catalog |

The full tree, with every collection and action, is on the [object tree](objects.md) page.

## Strongly typed, end to end

- Every argument, field and result is typed, and the package is checked with `mypy --strict` in CI.
- Responses are Pydantic models. Dates are `whenever.Instant`, amounts `Money` with `.to_decimal()`.
- Enumerations are open: a status or a commercial type Scaleway adds after a release is accepted, instead of failing the whole response.
- An argument naming another resource (`volume_id`) takes a string, a reference or an object.

## Versions out of sight

No class, module or attribute carries an API version. For each API, aioscaleway uses the latest stable version, and the latest preview when there is no stable one yet: 28 of the 53 products, including IAM, billing and domains, only exist in preview. A preview operation says so in its docstring.

## Reliable by default

Throttling (`429`) and transient failures (`502`, `503`, `504`, broken connections) are retried with stamina, honouring `Retry-After`. A `POST` is only retried when Scaleway cannot have processed it, so a creation is never sent twice. API errors are typed (`ResourceNotFoundError`, `QuotasExceededError`, `TransientStateError`...) and keep Scaleway's message.

## Complete

The code is generated from the OpenAPI files Scaleway publishes, committed in the repository: 59 API versions and about 1,500 operations. Every operation is reachable, through the objects or through `scw.raw`, and the [coverage](coverage.md) page says where.
