# Architecture

## Layout

- `src/aioscaleway/_client.py`, `_settings.py`, `_errors.py`, `_models.py`,
  `_enums.py`: the hand-written runtime, shared by every API.
- `src/aioscaleway/<product>/<version>/`: generated, one package per API
  version, with `models.py` (pydantic models and enums), `api.py` (the API
  classes) and an `__init__.py` re-exporting both. Never edited by hand: the
  first line of each file says so, and CI fails when they drift from `specs/`.
- `specs/`: the OpenAPI files as Scaleway publishes them, plus `index.tsv`,
  the URL each one was downloaded from.
- `scripts/`: the generator, the spec refresh and the release helpers.

## Following the official SDK

Product modules, versions and class names are those of the
[official SDK](https://github.com/scaleway/scaleway-sdk-python), so that an
import changes from `scaleway.` to `aioscaleway.` and nothing else. The
OpenAPI file names differ for a few products (`apple_silicon`, `containers`,
`secret_manager`...); `SDK_PRODUCT_NAMES` in the generator maps them back.
Products the official SDK does not ship (`generative_apis`, `reseller`) keep
the name of their OpenAPI file. A product split into several API classes
(`AccountV3ProjectAPI`, `AccountV3UserAPI`) shares one `models.py`.

Method names are the `operationId` in snake case (`ListConsumptions` becomes
`list_consumptions`), which is also what the official SDK uses.

## Where the specs come from

Scaleway publishes one OpenAPI 3.1 file per API on its developers website,
but no machine-readable index. The site is a Zudoku build whose entry bundle
lists every file with its route; `scripts/spec_index.py` extracts that list.
`scripts/fetch_specs.sh` downloads with `curl`, because the website refuses
the default client of Python HTTP libraries, then regenerates the code.
Refreshing is a deliberate step, reviewed in a merge request like any change:
the generated diff shows exactly what Scaleway changed.

## Generated models

- **Field defaults follow proto3.** Scaleway APIs are gRPC services exposed as
  JSON, where an absent scalar means its zero value. A field the spec does not
  mark as required defaults to `""`, `0`, `False`, an empty list or dict, or
  the enum's `unknown_*` member; a nullable field, or an object, defaults to
  `None`. Required fields have no default.
- **Enumerations are open** (`OpenStrEnum`): an unknown value becomes a pseudo
  member instead of a validation error. Scaleway adds statuses and commercial
  types regularly, and a closed enum would break every response that carries
  one.
- **Unknown fields are kept** (`extra="allow"`), for the same reason.
- **Dates are `datetime`**, timezone aware, as pydantic parses RFC 3339.
  A model is the boundary with the API, where the standard library type is the
  expected one; callers convert to `whenever` or anything else on their side.
- `google.type.Money` maps to the hand-written `Money`, whose `to_decimal()`
  avoids rebuilding the units and nanos arithmetic everywhere.
- **Unions written as duplicate keys.** The Generative APIs spec writes
  `content` twice, the second key padded with a zero-width space, to say
  "a string or a list of parts". The generator folds both into one field typed
  as the union.
- Field names that clash with pydantic (`json`, `schema`, `copy`) or Python
  keywords get a trailing underscore and an alias to the wire name.

## Requests

- Every argument is keyword-only. Path parameters are required, except
  `region` and `zone`, which fall back to the client defaults.
- `project_id` and `organization_id` in a request body fall back to the
  defaults too. When the spec says only one of the two may be set (a `oneOf`
  on `required`, or the `x-one-of` extension, as in the Instance API, which
  calls them `project` and `organization`), `ScalewayClient.owner` sends the
  given one, otherwise the default project, otherwise the default
  organization.
- `None` means "not sent", in the query string as in the body. Nested models
  are serialised with `exclude_unset`, so a model only carries the fields the
  caller set.

## Pagination

An operation gets `_iter` and `_all` variants when it is a `GET` with a
`page` query parameter and its response has a single list (or one whose name
appears in the operation name). The total comes from `total_count`, or from
the `X-Total-Count` header for the APIs that use it (Instance v1). The walk
stops on an empty page even when the total is unknown.

## Retries

`stamina` retries throttling and transient failures, waiting `Retry-After`
when Scaleway gives it. Idempotent methods (`GET`, `PUT`, `DELETE`) are
retried on `429`, `502`, `503`, `504` and transport errors. A `POST` is only
retried when the request cannot have been processed: `429`, `503`, or a
connection that never opened. Retrying a `POST` after a `502` could create a
second server.

## Dependencies

As a library, the package declares lower bounds (`httpx2>=2.16.0`) rather than
exact pins, so it does not fight the versions its users lock. The development
tools are pinned in `pyproject.toml` and every version, transitive ones
included, is locked in `uv.lock`, each released at least two weeks before it
was adopted.
