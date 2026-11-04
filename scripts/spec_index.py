"""Read the developers website bundle on stdin, print `name<TAB>schema URL` lines."""

import re
import sys

SITE = "https://www.scaleway.com"
# The site is a Zudoku build: its entry bundle lists every spec with its route.
API_ENTRY = re.compile(r"\{type:`file`,input:\[(.*?)\],path:`([^`]+)`")
VERSION_ENTRY = re.compile(
    r"\{path:`([^`]+)`,label:`[^`]*`,input:`openapi/openapi/([^`]+)\.yml`\}"
)


def spec_urls(bundle: str) -> dict[str, str]:
    urls: dict[str, str] = {}
    for api in API_ENTRY.finditer(bundle):
        inner, route = api.groups()
        for version in VERSION_ENTRY.finditer(inner):
            path = re.sub(r"/+", "/", f"/en/developers{route}/{version.group(1)}")
            urls.setdefault(version.group(2), f"{SITE}{path}/schema.yml")
    return urls


def main() -> None:
    urls = spec_urls(sys.stdin.read())
    if not urls:
        raise SystemExit("No OpenAPI file listed in the bundle.")
    for name, url in sorted(urls.items()):
        print(f"{name}\t{url}")


if __name__ == "__main__":
    main()
