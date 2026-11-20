"""Previous-bundle lookup failures: treat previous as empty, upload, fail the run."""

import sys

sys.path.insert(0, Test.TestDirectory)
from helpers import TOOL, bundle, setup, snapshot_run  # noqa: E402

Test.Summary = "Failed or unreadable previous lookup uploads a full set and fails the run"
setup(Test)

# 1. fetch-previous recorded a failure.
tr = snapshot_run(
    Test, When, "recorded lookup failure", "20260105T000000Z",
    previous="prev1",
    pre=f"{TOOL} status prev1 '{{\"status\": \"failed\", \"reason\": \"HTTPError: 500\"}}'",
)
tr.Processes.Default.ReturnCode = 1
tr.Processes.Default.Streams.stdout = All(
    Testers.ContainsExpression(r"Previous bundle lookup failed: HTTPError: 500", "reports lookup failure"),
    Testers.ContainsExpression(r"Upload: yes", "uploads full set"),
    Testers.ContainsExpression(r"Run status: FAILED", "run fails"),
)
tr.Disk.File(bundle("20260105T000000Z"), exists=True)

# 2. Previous dir is garbage (status says found, manifest missing).
tr = snapshot_run(
    Test, When, "unreadable previous manifest", "20260105T060000Z",
    previous="prev2",
    pre=f"{TOOL} status prev2 '{{\"status\": \"found\", \"bundle\": \"x\"}}'",
)
tr.Processes.Default.ReturnCode = 1
tr.Processes.Default.Streams.stdout = All(
    Testers.ContainsExpression(r"Previous bundle lookup failed: could not read previous manifest", "unreadable"),
    Testers.ContainsExpression(r"Upload: yes", "uploads full set"),
)

# 3. --previous points at an empty dir (fetch-previous never ran): also a failure.
tr = snapshot_run(
    Test, When, "missing status file", "20260105T120000Z",
    previous="prev3", pre="mkdir -p prev3",
)
tr.Processes.Default.ReturnCode = 1
tr.Processes.Default.Streams.stdout = Testers.ContainsExpression(
    r"Previous bundle lookup failed", "missing status is a failure")

# 4. fetch-previous found no artifacts at all: not a failure.
tr = snapshot_run(
    Test, When, "no previous artifacts is fine", "20260105T180000Z",
    previous="prev4", pre=f"{TOOL} status prev4 '{{\"status\": \"none\"}}'",
)
tr.Processes.Default.ReturnCode = 0
tr.Processes.Default.Streams.stdout = All(
    Testers.ContainsExpression(r"Previous bundle: none", "none"),
    Testers.ContainsExpression(r"Run status: ok", "run ok"),
)
