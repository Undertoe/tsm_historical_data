#!/usr/bin/env python3
"""Test helper: inspect bundles and fake `fetch-previous` output directories."""

import argparse
import json
import sys
import tarfile
from pathlib import Path


def read_manifest(bundle: Path) -> dict:
    with tarfile.open(bundle, "r:xz") as tar:
        return json.load(tar.extractfile("manifest.json"))


def cmd_show(args):
    with tarfile.open(args.bundle, "r:xz") as tar:
        for name in tar.getnames():
            print(f"member: {name}")
        manifest = json.load(tar.extractfile("manifest.json"))
    for name, digest in manifest.items():
        print(f"manifest: {name} {digest}")


def cmd_from_bundle(args):
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(Path(args.bundle))
    for name in args.zero or []:
        manifest[name] = "0" * 64
    (dest / "manifest.json").write_text(json.dumps(manifest))
    bundle_name = Path(args.bundle).name.removesuffix(".tar.xz")
    (dest / "status.json").write_text(json.dumps({"status": "found", "bundle": bundle_name}))


def cmd_status(args):
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "status.json").write_text(args.raw)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(required=True)
    s = sub.add_parser("show")
    s.add_argument("bundle")
    s.set_defaults(func=cmd_show)
    s = sub.add_parser("from-bundle")
    s.add_argument("bundle")
    s.add_argument("dest")
    s.add_argument("--zero", action="append")
    s.set_defaults(func=cmd_from_bundle)
    s = sub.add_parser("status", help="write a raw status.json")
    s.add_argument("dest")
    s.add_argument("raw")
    s.set_defaults(func=cmd_status)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
