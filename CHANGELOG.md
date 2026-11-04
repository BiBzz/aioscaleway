# Changelog

Notable changes to this project, newest first.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-05

First version published on PyPI.

### Added

- `Scaleway`, the client, read from the `SCW_*` variables of the Scaleway CLI,
  with `with_options()` to change defaults while sharing connections.
- Business areas shared with aioovh: `compute`, `storage`, `network`,
  `kubernetes`, `serverless`, `databases`, `analytics`, `messaging`, `ai`,
  `iot`, `email`, `domains`, `web_hosting`, `observability`, `iam`,
  `account`, `billing` and `orders`, covering the 59 API versions published
  on the Scaleway developers website.
- Collections iterated with `async for`, every page read, narrowed with
  `filter()`, with `pages()` for the totals a page carries; references that act without loading and load when awaited;
  loaded objects that are references too.
- One method per action, including one per value of the Instance server
  actions (`reboot()`, `power_off()`...).
- Typed errors under `ScalewayAPIError`, retries with `stamina`, dates as
  `whenever.Instant`, open enumerations, `Money.to_decimal()`.
- `scw.raw`, the underlying HTTP client, for anything else.
- Type information shipped with the package (`py.typed`).

[Unreleased]: https://gitlab.com/businessagile/libraries/aioscaleway/-/compare/v0.1.0...development
[0.1.0]: https://gitlab.com/businessagile/libraries/aioscaleway/-/tags/v0.1.0
