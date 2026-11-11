---
description: "Design principles, scope and roadmap of aioscaleway, the asynchronous and fully typed Python client for Scaleway."
---

# Design and roadmap

aioscaleway is developed in the open. This page states what it aims at, what it leaves out, and what comes next. Discussion happens in the [GitHub issues](https://github.com/BiBzz/aioscaleway/issues).

## Principles

1. **Async only.** No synchronous twin of the API: one way to do each thing.
2. **Objects, not URLs.** The public surface follows what you manipulate; paths and versions are details of the routing, chosen by the library.
3. **Types first.** If the type checker cannot follow it, it is not the API.
4. **Everything reachable.** Every operation Scaleway publishes is either an object method or explicitly left to the raw layer, and a test keeps it that way.
5. **Generated, then reviewed.** The code is generated from Scaleway's OpenAPI files; the names come from rules and from a mapping reviewed in merge requests, and the generator stops rather than guess a name.

## Two layers

- **Operations** (`aioscaleway._operations`), private: one typed method per OpenAPI operation, following Scaleway's products and versions.
- **Objects** (`aioscaleway.compute`, `aioscaleway.billing`...), public: business areas, collections, references and loaded objects, generated from the operations and `mapping.yaml`.

The [architecture](architecture.md) page details how operations become objects.

## Non goals

- A synchronous client.
- Object Storage: it speaks the S3 protocol, and S3 clients already do it well.
- Hiding the API: `scw.raw` reaches any path, and every object method says which call it makes.

## Roadmap

| Step | Content |
| --- | --- |
| 0.1 | Every API as objects, collections, references, actions, pages, typed errors, retries |
| 0.2 | `wait_until(state=...)` on resources with a life cycle (servers, clusters, databases) |
| 0.3 | References from fields that name another resource, `first()` and `count()` where the API allows it |
| 0.4 | Documentation examples executed by the test suite, recipes for FastAPI and task workers |
| later | A shared core with aioovh, then other European providers |

## Prior art

aioscaleway stands on what others built: the [official Scaleway SDK](https://github.com/scaleway/scaleway-sdk-python) for its OpenAPI files and naming, the [Stainless](https://www.stainless.com) generated SDKs (OpenAI, Anthropic, Cloudflare) for the resource tree, [hcloud-python](https://github.com/hetznercloud/hcloud-python) for bound objects, and the [Azure SDK design guidelines](https://azure.github.io/azure-sdk/python_design.html) for versions and paging.
