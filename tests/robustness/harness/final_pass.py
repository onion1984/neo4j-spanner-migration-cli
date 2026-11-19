"""Final evidence pass: re-assert authoritative records that later partial sessions may have superseded
with vacuous results (e.g. session-2/4 H-06 with no R2 verify), then build summary.md / defects.md.

Run after all sessions:  python -m harness.final_pass reports/<run-id>
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from harness import defect_log, findings


def main(report_dir: Path) -> None:
    findings.init(report_dir)
    recs = [json.loads(l) for l in (report_dir / "findings.jsonl").read_text().splitlines()]

    def latest_confirmed(test: str, hyp: str):
        c = [r for r in recs if r["test"] == test and r["hyp"] == hyp and r["status"] == "Confirmed"]
        return c[-1] if c else None

    for test, hyp in [("H-06", "H19"), ("D-08(T3)/G-04", "H07")]:
        r = latest_confirmed(test, hyp)
        if r:
            findings.record(hyp, test, "Confirmed", r["evidence"], severity=r["severity"], title=r["title"], workaround=r.get("workaround"))

    # A-04 empty mapping observation -> explicit finding
    empty = [r for r in recs if r["test"] == "A-04[empty_file]"]
    if empty and empty[-1]["status"] == "Observation":  # campaign-1 style record only
        findings.record("NEW-EMPTY", "A-04[empty_file]", "Confirmed",
                        "An empty schema_mapping.yaml is accepted by `export`, which exits 0 and reports "
                        "'Export complete: 0 node row(s), 0 edge row(s)'. " + empty[-1]["evidence"],
                        severity="P2", title="An empty schema_mapping.yaml exports 0 rows with exit code 0")
    defect_log.build(report_dir, severity_overrides={
        "H22": "P1",   # silent corruption: BrokenHydrationObject repr written to CSV
        "H09": "P1",   # only ARRAY/JSON conflicts fail (CAST(NULL AS STRING(MAX)) and INT->STRING are accepted)
        **({"H19": "P2"} if "c3e4" in report_dir.name else {}),  # campaign 3: only override-widened PKs remain affected
    })


if __name__ == "__main__":
    main(Path(sys.argv[1]))
