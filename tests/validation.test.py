"""Responses that are not real CSVs count as missing."""

import sys

sys.path.insert(0, Test.TestDirectory)
from helpers import bundle, setup, show_run, snapshot_run  # noqa: E402

Test.Summary = "HTML, empty, and comma-less responses are treated as missing"
setup(Test)

ZERO = "0" * 64

tr = snapshot_run(
    Test, When, "invalid responses are missing", "20260104T000000Z",
    pre=(
        "printf '<!doctype html><title>Error</title>' > site/realm/normal-horde/items.csv"
        " && : > site/realm/normal-alliance/items.csv"
        " && printf 'not a csv\\nat all\\n' > site/realm/pvp-alliance/items.csv"
    ),
)
tr.Processes.Default.ReturnCode = 1
tr.Processes.Default.Streams.stdout = All(
    Testers.ContainsExpression(r"realm_normal-horde_items.csv missing: response is HTML", "HTML rejected"),
    Testers.ContainsExpression(r"realm_normal-alliance_items.csv missing: empty response", "empty rejected"),
    Testers.ContainsExpression(r"realm_pvp-alliance_items.csv missing: first line has no comma", "no comma rejected"),
    Testers.ContainsExpression(r"3 required file\(s\) missing", "three missing"),
    Testers.ContainsExpression(r"Upload: yes", "valid files still upload"),
)

tr = show_run(Test, "invalid files have zero checksums", "20260104T000000Z")
tr.Processes.Default.Streams.stdout = All(
    Testers.ContainsExpression(f"manifest: realm_normal-horde_items.csv {ZERO}$", "html zeroed"),
    Testers.ContainsExpression(f"manifest: realm_normal-alliance_items.csv {ZERO}$", "empty zeroed"),
    Testers.ContainsExpression(f"manifest: realm_pvp-alliance_items.csv {ZERO}$", "no-comma zeroed"),
    Testers.ContainsExpression("member: region_items.csv$", "valid files bundled"),
)
