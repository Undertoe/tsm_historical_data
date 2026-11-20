# TSM Historical Data

Snapshots TradeSkillMaster's public pricing CSVs for WoW **Forever** (US) every
6 hours and keeps them as private GitHub Actions artifacts (36-day retention)
for pulling to a local machine. Design and decisions: [PLAN.md](PLAN.md).

Pricing data from TradeSkillMaster — https://tradeskillmaster.com. Bundles are
private; TSM's terms forbid republishing the data in bulk.

## What a run does

Runs at 05:17, 11:17, 17:17, 23:17 UTC and on every push to `main`.

1. `fetch-previous` finds the newest `tsm-forever-us-*` artifact and extracts
   its `manifest.json`.
2. `snapshot` downloads 8 realm files + the region file (plus the optional
   `NEUTRAL_TMP` placeholder), logs the first 5 lines of each, and compares
   checksums against the previous manifest.
3. If any downloaded file is new or changed, it writes a bundle and the
   workflow uploads it as an artifact.

The run is marked **failed** (GitHub emails you) if any required file is
missing or the previous-bundle lookup failed — after uploading whatever it got.

## Bundle layout

`tsm-forever-us-YYYYMMDDTHHMMSSZ.tar.xz` (UTC), flat:

```
manifest.json
realm_normal-horde_items.csv
realm_normal-alliance_items.csv
realm_pvp-horde_items.csv
realm_pvp-alliance_items.csv
realm_roleplay-horde_items.csv
realm_roleplay-alliance_items.csv
realm_roleplay-pvp-horde_items.csv
realm_roleplay-pvp-alliance_items.csv
region_items.csv
```

`manifest.json` maps each filename to the SHA-256 of its raw bytes. A missing
required file is listed with 64 zeros and is not in the tar. Sale-rate columns
(`saleRate`, `soldPerDay`, `avgSalePrice`) are only in `region_items.csv`.

## Downloading bundles

GitHub wraps each artifact in a `.zip`; the `.tar.xz` is inside.

```sh
gh run download --repo Undertoe/tsm_historical_data --pattern 'tsm-forever-us-*' --dir bundles
```

## Local run

Needs only Python 3.10+. Writes a bundle to `out/` without touching GitHub:

```sh
python3 tsm_snapshot.py snapshot --out out
```

Add `--previous DIR` to compare against a previous manifest (a directory with
`manifest.json` and `status.json` as written by `fetch-previous`).

## Tests

Functional tests use [AuTest](https://pypi.org/project/autest/) against a local
HTTP server serving `tests/fixtures/site`. They run on every pull request.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/autest -D tests --sandbox /tmp/autest-sandbox
```

On macOS the first run may show a firewall prompt for Python; the test server
only listens on `127.0.0.1`.
