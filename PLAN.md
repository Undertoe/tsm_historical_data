# TSM Historical Data — Plan

Collect TradeSkillMaster public pricing snapshots for WoW **Forever** (US) on a
schedule, hold them briefly as GitHub Actions artifacts, and pull them to a
local machine for long-term storage and analysis.

## Source

TSM public data: https://tradeskillmaster.com/public-data

URL pattern: `https://public-data.tradeskillmaster.com/forever/us/...`

| File | Path | Columns |
| --- | --- | --- |
| Realm items (×8) | `realm/{realm}/items.csv` | `itemId, name, marketValue, minBuyout, recent, historical, updatedAt` |
| Region items | `region/items.csv` | `itemId, name, marketValue, historical, avgSalePrice, saleRate, soldPerDay, updatedAt` |

Realm slugs (all verified 200 on 2026-11-19):

- `normal-horde`, `normal-alliance`
- `pvp-horde`, `pvp-alliance`
- `roleplay-horde`, `roleplay-alliance`
- `roleplay-pvp-horde`, `roleplay-pvp-alliance`

Notes:

- Prices are in copper. `updatedAt` is the upstream scan time, constant per file.
- Realm data updates every few hours; region data updates daily.
- Sale-rate data (`saleRate`, `soldPerDay`, `avgSalePrice`) exists **only** in
  the region file — region-wide, no realm or faction split.
- Not published for Forever: `commodities.csv`, `pets.csv`.
- No neutral auction house found (probed `neutral`, `normal-neutral`,
  `pvp-neutral`, `roleplay-neutral`, `roleplay-pvp-neutral` — all 404).

## Decisions

- **Scope:** Forever, US only. Required targets are the 8 realm/side files plus
  the region file.
- **Neutral stub:** an optional target with the placeholder slug `NEUTRAL_TMP`
  (no real slug exists yet). Any failure of it is silent; a successful download
  is included in the bundle. Replace the placeholder if TSM ever publishes
  neutral data.
- **Visibility:** repo and artifacts stay private (see Terms below).
- **Storage:** one Actions artifact per uploaded bundle, 36-day retention. No
  appending or merging in Actions — the local machine is the long-term store.
- **Pull cadence (manual, local):** roughly weekly, with a ~10-day window.
- **Repo layout:** this repo will also host the analysis tooling and tests, so
  format changes and the code that reads bundles stay in sync. Data never lives
  in the repo.

## Triggers

| Event | What runs |
| --- | --- |
| Schedule: 05:17, 11:17, 17:17, 23:17 UTC | Full snapshot |
| Push to `main` (every merge, no path filter) | Full snapshot |
| PR opened / pushed to | Tests only, against sample CSVs in the repo. No TSM download, no upload |

- No manual trigger.
- Schedule times are 23:17, 05:17, 11:17, 17:17 CST: off the top of the hour
  and clear of the 08:00 CST maintenance window. Retune once collected
  `updatedAt` values reveal TSM's real update cadence.
- The first merge has no previous bundle, so it always uploads — that is the
  end-to-end check of the Actions side.
- No run coordination. Overlapping runs are rare (a run takes ~1 minute); an
  occasional near-duplicate bundle is acceptable.

## Responsibilities

- **Python script (stdlib only)** makes every decision: fetch, validate,
  build the manifest, compare against the previous manifest, decide whether to
  upload, decide run status.
- **Workflow YAML** stays minimal: triggers, call the script, upload if the
  script says so. Finding and reading the previous artifact is also done by
  the script (`fetch-previous` subcommand, GitHub API via stdlib), so a lookup
  failure is detected and tested in Python.
- **Local mode:** the script can run on a local machine — fetch from TSM, build
  the bundle and manifest into a chosen directory, print the same logs, and
  optionally compare against a given previous manifest. It never talks to
  GitHub.

## Run behaviour

### Fetch and validate

- Each required target: up to 5 attempts, 1 minute apart, 60-second timeout
  per attempt. The optional `NEUTRAL_TMP` target gets a single attempt.
- Up to 4 downloads run in parallel.
- A file is **ok** when all of these hold:
  - HTTP 200
  - non-empty
  - not HTML (first non-whitespace character is not `<`)
  - first line contains a comma
- Otherwise the file is **missing**. Column changes are not errors — a changed
  header is captured as a change.
- Every run logs the first 5 lines of each downloaded CSV so `updatedAt`
  timestamps can be checked by hand.

### Bundle

- All raw, unmodified CSVs plus the manifest in one tar, compressed with
  `xz -9e`.
- Name: `tsm-forever-us-YYYYMMDDTHHMMSSZ.tar.xz` (UTC, workflow start time).
  Sorts lexically, so the newest bundle is identifiable by name. The artifact
  uses the same name.
- Files are flat inside the tar, named by the URL path with `/` replaced by
  `_`; slugs keep their hyphens:
  - `realm_normal-horde_items.csv` … (one per realm)
  - `region_items.csv`
  - `manifest.json`

### Manifest

- One entry per file: filename → SHA-256 of the raw bytes. Nothing else.
- A missing **required** file gets an entry with the zero checksum (64 `0`s).
- An absent **optional** file (`NEUTRAL_TMP`) gets no entry.

### Change detection

Each run downloads the most recent previous artifact and reads only its
manifest, then compares checksums per file:

> Upload if at least one file present in this run is new or differs from the
> previous bundle. Files missing in this run are ignored. A zero checksum in
> the previous bundle never matches.

| This run vs previous bundle | Upload? |
| --- | --- |
| All files identical | No |
| Any file changed | Yes |
| Has a file the previous bundle lacked or had as zero | Yes |
| Missing a file, rest identical | No |
| Missing a file, some file changed | Yes |
| No previous bundle | Yes |

A file recovering after a partial bundle counts as new even if it matches an
older bundle — the extra bundle is kept. When nothing uploads, the run logs
which previous bundle it matched.

### Run status

GitHub emails on failed runs, so "failed" is the alert channel.

| Situation | Upload | Run status |
| --- | --- | --- |
| All required files ok | Per change rule | Success |
| Some required files missing | Per change rule | **Failed** |
| All required files missing | Nothing to upload | **Failed** |
| Previous-artifact lookup fails | Treat previous as empty → upload full set | **Failed** |

Repeated lookup failures point at a problem with the pipeline itself.

## Terms

From the "Terms of Use" on the public-data page (read 2026-11-19):

- Free use in your own spreadsheets, addons, bots, websites and tools,
  including paid ones; showing prices inside your own product is fine.
- "Do not sell the data itself, or republish it in bulk as your own data feed
  or dataset." — hence private artifacts; public bulk access would need TSM's
  permission.
- Wherever data is shown to others, credit "Pricing data from TradeSkillMaster"
  with a link to tradeskillmaster.com.
- "Download each file at most once per update." 6-hourly polling stays within
  this; the change check reads our own artifact, not TSM; PR runs don't
  download.
- Automated access is explicitly allowed for the public data files
  (Terms of Service §3).

## Sizing

Measured 2026-11-19, one snapshot (9 CSVs):

| | Size |
| --- | --- |
| Raw | ~4.2 MB |
| gzip -9 | 1.25 MB |
| zstd -19 | 0.71 MB |
| xz -9e | 0.69 MB |

Worst case 4/day × 36 days = 144 artifacts ≈ 100 MB, under the 500 MB free
artifact quota. Change detection will usually make it less.

## Caveats

- GitHub downloads always wrap an artifact in a `.zip`; the `.tar.xz` is inside.
- Cron runs can drift by several minutes.
- TSM may change format or stop publishing at any time. Column changes are
  captured, not rejected; a stop in publishing shows up as failed runs.

## Stage 1 — Pipeline (this branch: `setup-pipeline`)

- `tsm_snapshot.py` — `snapshot` (also the local mode) and `fetch-previous`.
- AuTest functional tests in `tests/` against a local HTTP server serving
  sample CSVs.
- `.github/workflows/` — scheduled + merge snapshot run; PR test run.
- `README.md` — what it collects, bundle and manifest layout, how to download.

## Watch for later

- Repeatedly undersized files may mean the pipeline (or TSM) is returning bad
  data while still passing validation. Worth an alert eventually; not built now.

## Later (not yet designed)

- Analysis tooling: ad-hoc scripts/notebooks plus a small CLI (pull, ingest,
  query).
- Data location: an external mount outside this repo; how the repo finds it is
  undecided.
