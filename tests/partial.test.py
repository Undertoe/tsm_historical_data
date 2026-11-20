"""Partial runs: missing files get zero checksums, fail the run, and follow the upload rule."""

import sys

sys.path.insert(0, Test.TestDirectory)
from helpers import FIXTURE_SITE, TOOL, bundle, setup, show_run, snapshot_run  # noqa: E402

Test.Summary = "Missing required files: zero checksum, failed run, upload only on real change"
setup(Test)

ZERO = "0" * 64

# 1. One realm missing, no previous: the rest uploads, run fails.
tr = snapshot_run(
    Test, When, "partial run uploads and fails", "20260102T000000Z",
    pre="rm site/realm/pvp-horde/items.csv",
)
tr.Processes.Default.ReturnCode = 1
tr.Processes.Default.Streams.stdout = All(
    Testers.ContainsExpression(
        r"realm_pvp-horde_items.csv missing: HTTP 404 after 2 attempt\(s\)", "reports missing file"),
    Testers.ContainsExpression(r"Upload: yes", "still uploads"),
    Testers.ContainsExpression(r"Run status: FAILED", "run fails"),
)
tr.Disk.File(bundle("20260102T000000Z"), exists=True)

# 2. Missing file has a zero checksum and is not in the bundle.
tr = show_run(Test, "zero checksum for missing file", "20260102T000000Z")
tr.Processes.Default.Streams.stdout = All(
    Testers.ContainsExpression(f"manifest: realm_pvp-horde_items.csv {ZERO}$", "zero checksum"),
    Testers.ExcludesExpression("member: realm_pvp-horde_items.csv", "missing file not bundled"),
)

# 3. Still missing, rest identical: no upload, still fails.
tr = snapshot_run(
    Test, When, "still missing, nothing new: no upload", "20260102T060000Z",
    previous="prev3", pre=f"{TOOL} from-bundle {bundle('20260102T000000Z')} prev3",
)
tr.Processes.Default.ReturnCode = 1
tr.Processes.Default.Streams.stdout = All(
    Testers.ContainsExpression(
        r"Upload: no \(no change since tsm-forever-us-20260102T000000Z\)", "no upload"),
    Testers.ContainsExpression(r"Run status: FAILED", "run fails"),
)
tr.Disk.File(bundle("20260102T060000Z"), exists=False)

# 4. Still missing, but another file changed: upload, still fails.
tr = snapshot_run(
    Test, When, "still missing, other file changed: upload", "20260102T120000Z",
    previous="prev4",
    pre=(f"{TOOL} from-bundle {bundle('20260102T000000Z')} prev4"
         " && echo '999,Changed Item,1,1,1,1,1,2026-01-02T12:00:00Z' >> site/region/items.csv"),
)
tr.Processes.Default.ReturnCode = 1
tr.Processes.Default.Streams.stdout = All(
    Testers.ContainsExpression(r"Changed/new files: region_items.csv$", "region changed"),
    Testers.ContainsExpression(r"Upload: yes", "uploads"),
)

# 5. Missing file comes back unchanged: zero in previous never matches, so it is new.
tr = snapshot_run(
    Test, When, "recovered file counts as new", "20260102T180000Z",
    previous="prev5",
    pre=(f"{TOOL} from-bundle {bundle('20260102T120000Z')} prev5"
         f" && cp {FIXTURE_SITE}/realm/pvp-horde/items.csv site/realm/pvp-horde/items.csv"),
)
tr.Processes.Default.ReturnCode = 0
tr.Processes.Default.Streams.stdout = All(
    Testers.ContainsExpression(r"Changed/new files: realm_pvp-horde_items.csv$", "recovered file is new"),
    Testers.ContainsExpression(r"Run status: ok", "run ok"),
)

# 6. Everything missing: nothing to upload, run fails.
tr = snapshot_run(
    Test, When, "all missing: no upload, fails", "20260103T000000Z",
    previous="prev6",
    pre=f"{TOOL} from-bundle {bundle('20260102T180000Z')} prev6 && rm -rf site/realm site/region",
)
tr.Processes.Default.ReturnCode = 1
tr.Processes.Default.Streams.stdout = All(
    Testers.ContainsExpression(r"Upload: no \(no files downloaded\)", "nothing downloaded"),
    Testers.ContainsExpression(r"9 required file\(s\) missing", "all required missing"),
    Testers.ContainsExpression(r"Run status: FAILED", "run fails"),
)
tr.Disk.File(bundle("20260103T000000Z"), exists=False)
