#!/usr/bin/env python3
"""TSM Forever (US) snapshot pipeline. Standard library only.

Subcommands:
  snapshot        Fetch the TSM CSVs, build the manifest, compare against the
                  previous manifest, and write a bundle if anything changed.
                  Never talks to GitHub, so it is also the local mode.
  fetch-previous  (GitHub Actions only) Find the newest previous bundle
                  artifact and extract its manifest for `snapshot --previous`.

See PLAN.md for the rules this implements.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import io
import json
import lzma
import os
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

BASE_URL = "https://public-data.tradeskillmaster.com/forever/us"
BUNDLE_PREFIX = "tsm-forever-us-"
MANIFEST_NAME = "manifest.json"
STATUS_NAME = "status.json"
ZERO_SHA = "0" * 64
USER_AGENT = "tsm-historical-data-snapshot"

REALMS = [
    "normal-horde",
    "normal-alliance",
    "pvp-horde",
    "pvp-alliance",
    "roleplay-horde",
    "roleplay-alliance",
    "roleplay-pvp-horde",
    "roleplay-pvp-alliance",
]

# Placeholder: TSM publishes no neutral auction house data for Forever yet.
NEUTRAL_SLUG = "NEUTRAL_TMP"


@dataclass(frozen=True)
class Target:
    path: str  # URL path relative to the base URL, e.g. "realm/pvp-horde/items.csv"
    required: bool

    @property
    def filename(self) -> str:
        return self.path.replace("/", "_")


TARGETS = [Target(f"realm/{slug}/items.csv", True) for slug in REALMS] + [
    Target("region/items.csv", True),
    Target(f"realm/{NEUTRAL_SLUG}/items.csv", False),
]


@dataclass
class FetchResult:
    target: Target
    data: bytes | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.data is not None


# --------------------------------------------------------------------------
# Logging


def _in_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def log_error(msg: str) -> None:
    # Annotations surface in the Actions run summary and failure email.
    print(f"::error::{msg}" if _in_actions() else f"ERROR: {msg}", flush=True)


def log_warning(msg: str) -> None:
    print(f"::warning::{msg}" if _in_actions() else f"WARNING: {msg}", flush=True)


def set_output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            fh.write(f"{key}={value}\n")


# --------------------------------------------------------------------------
# Fetch and validate


def validate(data: bytes) -> str | None:
    """Return None if `data` looks like a real CSV, else the reason it does not."""
    if not data.strip():
        return "empty response"
    if data.lstrip()[:1] == b"<":
        return "response is HTML, not CSV"
    first_line = data.split(b"\n", 1)[0]
    if b"," not in first_line:
        return "first line has no comma"
    return None


def fetch_once(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}")
        return resp.read()


def fetch_target(
    target: Target, base_url: str, attempts: int, retry_delay: float, timeout: float
) -> FetchResult:
    url = f"{base_url.rstrip('/')}/{target.path}"
    # Optional targets get a single attempt: their failure is expected and silent.
    tries = attempts if target.required else 1
    error = "not attempted"
    for attempt in range(1, tries + 1):
        try:
            data = fetch_once(url, timeout)
            problem = validate(data)
            if problem is None:
                return FetchResult(target, data)
            error = problem
        except urllib.error.HTTPError as exc:
            error = f"HTTP {exc.code}"
        except Exception as exc:  # network errors, timeouts, etc.
            error = f"{type(exc).__name__}: {exc}"
        if attempt < tries:
            time.sleep(retry_delay)
    return FetchResult(target, None, f"{error} after {tries} attempt(s) ({url})")


def fetch_all(base_url: str, attempts: int, retry_delay: float, timeout: float) -> list[FetchResult]:
    # A few at a time: fast enough, and polite to TSM's host.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(fetch_target, t, base_url, attempts, retry_delay, timeout)
            for t in TARGETS
        ]
        return [f.result() for f in futures]


# --------------------------------------------------------------------------
# Manifest and change detection


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_manifest(results: list[FetchResult]) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for r in results:
        if r.ok:
            manifest[r.target.filename] = sha256(r.data)
        elif r.target.required:
            manifest[r.target.filename] = ZERO_SHA
        # absent optional targets get no entry
    return dict(sorted(manifest.items()))


def changed_files(current: dict[str, str], previous: dict[str, str]) -> list[str]:
    """Files present in this run that are new or differ from the previous bundle.

    Missing files in this run (zero checksum) are ignored. A zero checksum in
    the previous bundle never matches, because a real checksum is never zero.
    """
    return [
        name
        for name, digest in current.items()
        if digest != ZERO_SHA and previous.get(name) != digest
    ]


@dataclass
class Previous:
    status: str  # "none" | "found" | "failed"
    manifest: dict[str, str]
    bundle: str | None = None
    reason: str | None = None


def load_previous(directory: Path | None) -> Previous:
    if directory is None:
        return Previous("none", {})
    try:
        status = json.loads((directory / STATUS_NAME).read_text(encoding="utf-8"))
        kind = status["status"]
        if kind == "none":
            return Previous("none", {})
        if kind == "failed":
            return Previous("failed", {}, reason=status.get("reason", "unknown"))
        if kind != "found":
            raise ValueError(f"unknown status {kind!r}")
        manifest = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in manifest.items()
        ):
            raise ValueError("manifest is not a filename -> sha256 mapping")
        return Previous("found", manifest, bundle=status.get("bundle"))
    except Exception as exc:
        return Previous("failed", {}, reason=f"could not read previous manifest: {exc}")


# --------------------------------------------------------------------------
# Bundle


def bundle_name(timestamp: str) -> str:
    return f"{BUNDLE_PREFIX}{timestamp}"


def write_bundle(path: Path, results: list[FetchResult], manifest: dict[str, str]) -> None:
    members: list[tuple[str, bytes]] = [
        (r.target.filename, r.data) for r in results if r.ok
    ]
    members.append((MANIFEST_NAME, (json.dumps(manifest, indent=2) + "\n").encode()))
    mtime = int(time.time())
    with tarfile.open(path, "w:xz", preset=9 | lzma.PRESET_EXTREME) as tar:
        for name, data in sorted(members):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = mtime
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))


# --------------------------------------------------------------------------
# snapshot command


def cmd_snapshot(args: argparse.Namespace) -> int:
    timestamp = args.timestamp or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = bundle_name(timestamp)
    log(f"Snapshot {name}")

    previous = load_previous(Path(args.previous) if args.previous else None)
    results = fetch_all(args.base_url, args.attempts, args.retry_delay, args.timeout)

    # Per-file report, with the first lines of each CSV for eyeballing updatedAt.
    for r in results:
        if r.ok:
            log(f"\n== {r.target.filename} ok ({len(r.data)} bytes, sha256 {sha256(r.data)})")
            for line in r.data.decode("utf-8", errors="replace").splitlines()[:5]:
                log(f"   {line}")
        elif r.target.required:
            log_error(f"{r.target.filename} missing: {r.error}")
        else:
            log(f"\n== {r.target.filename} optional, not present ({r.error})")

    manifest = build_manifest(results)
    missing = [r.target.filename for r in results if r.target.required and not r.ok]

    log("")
    if previous.status == "found":
        log(f"Previous bundle: {previous.bundle}")
    elif previous.status == "none":
        log("Previous bundle: none")
    else:
        log_error(f"Previous bundle lookup failed: {previous.reason}. Treating previous as empty.")

    changes = changed_files(manifest, previous.manifest)
    upload = bool(changes)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = out_dir / f"{name}.tar.xz"

    if upload:
        write_bundle(bundle_path, results, manifest)
        log(f"Changed/new files: {', '.join(changes)}")
        log(f"Upload: yes -> {bundle_path} ({bundle_path.stat().st_size} bytes)")
    elif not any(r.ok for r in results):
        log("Upload: no (no files downloaded)")
    else:
        log(f"Upload: no (no change since {previous.bundle})")

    set_output(
        upload="true" if upload else "false",
        bundle_name=name,
        bundle_path=str(bundle_path),
    )

    failed = False
    if missing:
        log_error(f"{len(missing)} required file(s) missing: {', '.join(missing)}")
        failed = True
    if previous.status == "failed":
        failed = True
    log(f"Run status: {'FAILED' if failed else 'ok'}")
    return 1 if failed else 0


# --------------------------------------------------------------------------
# fetch-previous command (GitHub Actions)


class _NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    """Artifact downloads redirect to blob storage, which rejects our token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.remove_header("Authorization")
        return new


def _github_get(url: str, token: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        },
    )
    req.add_unredirected_header("Authorization", f"Bearer {token}")
    opener = urllib.request.build_opener(_NoAuthRedirect)
    with opener.open(req, timeout=timeout) as resp:
        return resp.read()


def find_latest_artifact(api: str, repo: str, token: str) -> dict | None:
    candidates = []
    for page in range(1, 11):
        body = json.loads(
            _github_get(f"{api}/repos/{repo}/actions/artifacts?per_page=100&page={page}", token)
        )
        artifacts = body.get("artifacts", [])
        candidates += [
            a for a in artifacts if a["name"].startswith(BUNDLE_PREFIX) and not a.get("expired")
        ]
        if len(artifacts) < 100:
            break
    # Bundle names embed a sortable UTC timestamp.
    return max(candidates, key=lambda a: a["name"]) if candidates else None


def extract_manifest(artifact_zip: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(artifact_zip)) as zf:
        bundles = [n for n in zf.namelist() if n.endswith(".tar.xz")]
        if len(bundles) != 1:
            raise ValueError(f"expected one .tar.xz in artifact, found {bundles}")
        with tarfile.open(fileobj=io.BytesIO(zf.read(bundles[0])), mode="r:xz") as tar:
            member = tar.extractfile(MANIFEST_NAME)
            if member is None:
                raise ValueError("manifest.json is not a regular file")
            return member.read()


def cmd_fetch_previous(args: argparse.Namespace) -> int:
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    def write_status(**status: str) -> None:
        (dest / STATUS_NAME).write_text(json.dumps(status) + "\n", encoding="utf-8")

    try:
        token = os.environ["GITHUB_TOKEN"]
        repo = os.environ["GITHUB_REPOSITORY"]
        api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
        latest = find_latest_artifact(api, repo, token)
        if latest is None:
            log("No previous bundle artifact found.")
            write_status(status="none")
            return 0
        log(f"Previous bundle artifact: {latest['name']} (id {latest['id']})")
        data = _github_get(f"{api}/repos/{repo}/actions/artifacts/{latest['id']}/zip", token)
        (dest / MANIFEST_NAME).write_bytes(extract_manifest(data))
        write_status(status="found", bundle=latest["name"])
    except Exception as exc:
        # Recorded, not raised: `snapshot` decides what a failed lookup means.
        log_warning(f"Previous bundle lookup failed: {type(exc).__name__}: {exc}")
        write_status(status="failed", reason=f"{type(exc).__name__}: {exc}")
    return 0


# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="fetch, compare, and bundle")
    snap.add_argument("--out", required=True, help="directory to write the bundle into")
    snap.add_argument("--previous", help="directory written by fetch-previous (omit for no previous)")
    snap.add_argument("--base-url", default=BASE_URL)
    snap.add_argument("--attempts", type=int, default=5)
    snap.add_argument("--retry-delay", type=float, default=60, help="seconds between attempts")
    snap.add_argument("--timeout", type=float, default=60, help="seconds per attempt")
    snap.add_argument("--timestamp", help="override the UTC timestamp (YYYYMMDDTHHMMSSZ)")
    snap.set_defaults(func=cmd_snapshot)

    prev = sub.add_parser("fetch-previous", help="(Actions) fetch the previous bundle's manifest")
    prev.add_argument("--dest", required=True)
    prev.set_defaults(func=cmd_fetch_previous)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
