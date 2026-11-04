# Changelog

Notable changes to this project, newest first.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-04

First version published on PyPI.

### Added

- `ScalewayClient`, an asynchronous client on `httpx2` that authenticates with
  `X-Auth-Token` and retries throttling and transient failures with `stamina`.
- `ScalewaySettings`, read from the `SCW_*` environment variables of the
  Scaleway CLI.
- Typed errors: `ResourceNotFoundError`, `InvalidArgumentsError`,
  `QuotasExceededError`, `TransientStateError` and the rest of the Scaleway
  error types, all under `ScalewayAPIError`.
- Generated API classes and pydantic models for the 59 API versions published
  on the Scaleway developers website, with the module and class names of the
  official SDK.
- `_iter` and `_all` variants for every paginated listing.
- Open enumerations, which accept values added by Scaleway after generation.
- `Money.to_decimal()`.
- Type information shipped with the package (`py.typed`).

[Unreleased]: https://gitlab.com/businessagile/libraries/aioscaleway/-/compare/v0.1.0...development
[0.1.0]: https://gitlab.com/businessagile/libraries/aioscaleway/-/tags/v0.1.0
