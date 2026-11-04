#!/usr/bin/env bash
#
# Refresh specs/ from the Scaleway developers website, then regenerate the code.

set -euo pipefail

cd "$(dirname "$0")/.."
site="https://www.scaleway.com"
entry="$(curl -fsSL "${site}/en/developers/api/" |
    grep -oE '/en/developers/assets/entry[A-Za-z0-9._-]*\.js' | head -1)"
[ -n "$entry" ] || { echo "fetch_specs: no entry bundle on the index" >&2; exit 1; }

curl -fsSL "${site}${entry}" | uv run python scripts/spec_index.py >specs/index.tsv.new
mv specs/index.tsv.new specs/index.tsv
rm -f specs/scaleway.*.yml
while IFS=$'\t' read -r name url; do
    curl -fsSL "$url" -o "specs/${name}.yml"
    head -c 8 "specs/${name}.yml" | grep -q '^openapi' ||
        { echo "fetch_specs: ${url} is not an OpenAPI document" >&2; exit 1; }
done <specs/index.tsv

uv run python scripts/generate.py
