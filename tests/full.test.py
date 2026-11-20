"""Full snapshots: first upload, no-change skip, changed file, optional neutral file."""

import os
import sys

sys.path.insert(0, Test.TestDirectory)
from helpers import TOOL, bundle, setup, show_run, snapshot_run  # noqa: E402

Test.Summary = "Full snapshot, unchanged rerun, changed file, neutral placeholder appears"
setup(Test)

REALM_FILES = [
    f"realm_{slug}_items.csv"
    for slug in (
        "normal-horde", "normal-alliance", "pvp-horde", "pvp-alliance",
        "roleplay-horde", "roleplay-alliance", "roleplay-pvp-horde", "roleplay-pvp-alliance",
    )
]
ALL_FILES = REALM_FILES + ["region_items.csv"]

# 1. No previous bundle: everything is new, so it uploads.
tr = snapshot_run(Test, When, "first snapshot uploads", "20260101T000000Z")
tr.Processes.Default.ReturnCode = 0
tr.Processes.Default.Streams.stdout = All(
    Testers.ContainsExpression("Previous bundle: none", "no previous bundle"),
    Testers.ContainsExpression(r"Upload: yes", "uploads"),
    Testers.ContainsExpression(r"Run status: ok", "run ok"),
    Testers.ContainsExpression(r"realm_NEUTRAL_TMP_items.csv optional, not present", "neutral is silent"),
    Testers.ContainsExpression(r"itemId,name,marketValue,minBuyout", "logs CSV head lines"),
    Testers.ExcludesExpression(r"ERROR", "no errors"),
)
tr.Disk.File(bundle("20260101T000000Z"), exists=True)

# 2. Bundle layout: flat files plus manifest; no neutral entry.
tr = show_run(Test, "bundle has flat files and manifest", "20260101T000000Z")
tr.Processes.Default.Streams.stdout = All(
    *[Testers.ContainsExpression(f"member: {f}$", f"bundle contains {f}") for f in ALL_FILES],
    Testers.ContainsExpression("member: manifest.json$", "bundle contains manifest"),
    *[Testers.ContainsExpression(f"manifest: {f} [0-9a-f]{{64}}$", f"manifest lists {f}") for f in ALL_FILES],
    Testers.ExcludesExpression("NEUTRAL", "absent optional file has no manifest entry"),
    Testers.ExcludesExpression("manifest: .* 0{64}$", "no zero checksums"),
)

# 3. Same data again: no upload.
tr = snapshot_run(
    Test, When, "unchanged data does not upload", "20260101T060000Z",
    previous="prev2", pre=f"{TOOL} from-bundle {bundle('20260101T000000Z')} prev2",
)
tr.Processes.Default.ReturnCode = 0
tr.Processes.Default.Streams.stdout = All(
    Testers.ContainsExpression(
        r"Upload: no \(no change since tsm-forever-us-20260101T000000Z\)", "skips unchanged"),
    Testers.ContainsExpression(r"Run status: ok", "run ok"),
)
tr.Disk.File(bundle("20260101T060000Z"), exists=False)

# 4. One file changes: upload, and only that file is reported as changed.
tr = snapshot_run(
    Test, When, "changed region file uploads", "20260101T120000Z",
    previous="prev3",
    pre=(f"{TOOL} from-bundle {bundle('20260101T000000Z')} prev3"
         " && echo '999,Changed Item,1,1,1,1,1,2026-01-01T12:00:00Z' >> site/region/items.csv"),
)
tr.Processes.Default.ReturnCode = 0
tr.Processes.Default.Streams.stdout = All(
    Testers.ContainsExpression(r"Changed/new files: region_items.csv$", "only region changed"),
    Testers.ContainsExpression(r"Upload: yes", "uploads"),
)
tr.Disk.File(bundle("20260101T120000Z"), exists=True)

# 5. Neutral placeholder starts being served: it is new, so it uploads and is bundled.
tr = snapshot_run(
    Test, When, "neutral file appears", "20260101T180000Z",
    previous="prev4",
    pre=(f"{TOOL} from-bundle {bundle('20260101T120000Z')} prev4"
         " && mkdir -p site/realm/NEUTRAL_TMP"
         " && cp site/realm/normal-horde/items.csv site/realm/NEUTRAL_TMP/items.csv"),
)
tr.Processes.Default.ReturnCode = 0
tr.Processes.Default.Streams.stdout = All(
    Testers.ContainsExpression(r"Changed/new files: realm_NEUTRAL_TMP_items.csv$", "neutral is new"),
    Testers.ContainsExpression(r"Run status: ok", "run ok"),
)
tr = show_run(Test, "neutral file is bundled", "20260101T180000Z")
tr.Processes.Default.Streams.stdout = Testers.ContainsExpression(
    "member: realm_NEUTRAL_TMP_items.csv$", "bundle contains neutral file")
