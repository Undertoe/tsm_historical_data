"""Shared setup for the AuTest functional tests.

Each test copies tests/fixtures/site into its sandbox as `site/` and serves it
with a local HTTP server standing in for public-data.tradeskillmaster.com.
"""

import os
import shlex
import socket
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS_DIR)
PY = shlex.quote(sys.executable)
SCRIPT = shlex.quote(os.path.join(REPO, "tsm_snapshot.py"))
TOOL = f"{PY} {shlex.quote(os.path.join(TESTS_DIR, 'tools', 'prev_tool.py'))}"
SERVE = f"{PY} {shlex.quote(os.path.join(TESTS_DIR, 'tools', 'serve.py'))}"
FIXTURE_SITE = os.path.join(TESTS_DIR, "fixtures", "site")

# Keep a CI environment from leaking into the script under test.
CLEAN_ENV = "env -u GITHUB_OUTPUT -u GITHUB_ACTIONS"


def bundle(ts):
    return f"out/tsm-forever-us-{ts}.tar.xz"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def setup(Test):
    Test.Setup.Copy(FIXTURE_SITE, "site")


def snapshot_run(Test, When, name, ts, previous=None, pre=None):
    """Add a TestRun that serves `site/` and runs a snapshot against it.

    `pre` is a shell command run first (e.g. to mutate site/ or build a
    previous dir). Retries are shortened so missing files fail fast.
    """
    tr = Test.AddTestRun(name)
    port = free_port()
    server = tr.Processes.Process(
        f"server{port}", f"{SERVE} {port} site"
    )
    cmd = (
        f"{CLEAN_ENV} {PY} {SCRIPT} snapshot --out out"
        f" --base-url http://127.0.0.1:{port}"
        f" --attempts 2 --retry-delay 0 --timeout 5 --timestamp {ts}"
    )
    if previous:
        cmd += f" --previous {previous}"
    if pre:
        cmd = f"{pre} && {cmd}"
    tr.Processes.Default.Command = cmd
    tr.Processes.Default.StartBefore(server, ready=When.PortOpen(port))
    return tr


def show_run(Test, name, ts):
    tr = Test.AddTestRun(name)
    tr.Processes.Default.Command = f"{TOOL} show {bundle(ts)}"
    tr.Processes.Default.ReturnCode = 0
    return tr
