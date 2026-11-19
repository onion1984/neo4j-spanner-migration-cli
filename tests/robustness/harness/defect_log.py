"""Build reports/<run-id>/summary.md and defects.md from findings.jsonl.

Usage: python -m harness.defect_log <report_dir>
Later records for the same test id supersede earlier ones (re-runs after harness fixes).
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict
import json
from pathlib import Path
import sys

HYP_TITLES = {
    "H01": "verify cannot catch coercion bugs (shares coerce_value())",
    "H02": "DateTime ns truncated to µs; verify compares only to ms",
    "H03": "INT64+FLOAT64 widening loses precision > 2^53; verify isclose hides it",
    "H04": "Type overrides not validated (truncation / silent false / invalid DDL types)",
    "H05": "pk_overrides not checked for uniqueness or legal PK type",
    "H06": "Mixed-type unique keys collapse to duplicate STRING PKs",
    "H07": "NaN/Infinity inside lists -> invalid JSON",
    "H08": "Same property name, different types across node labels breaks graph DDL",
    "H09": "Conflicting ARRAY/JSON types on a shared edge label emit an invalid CAST (CAST(NULL AS STRING(MAX)) and INT->STRING are accepted)",
    "H10": "Secondary labels not queryable as GQL labels",
    "H11": "FK/index name truncation collisions",
    "H12": "dst_ prefix exceeds 128 chars",
    "H13": "Backtick escaping in graph DDL",
    "H14": "Delimiter '~' breaks Dataflow parameter separator",
    "H15": "--gcs-prefix / --graph-name injection",
    "H16": "Stale shards loaded (local dir / GCS prefix)",
    "H17": "0-row table -> manifest glob matches nothing",
    "H18": "--sample-size type drift crashes export with partial bundle",
    "H19": "verify false missing_in_neo4j for widened/TIMESTAMP/BYTES PKs",
    "H20": "verify sampling limited to first 50k rows",
    "H21": "Runbook not idempotent / no resume",
    "H22": "Out-of-range dates crash / corrupt export",
    "H23": "Spanner column limit not detected",
    "H24": "No driver timeout; stalled Neo4j hangs export",
    "H25": "Empty DB -> invalid NODE TABLES ()",
    "H26": "Unknown/missing YAML keys -> raw TypeError",
    "H27": "Writes during export -> dangling edges",
    "H28": "Neo4j 2025.x calendar versioning",
    "H29": "Multi-label partition drops/duplicates rows",
}

WORKAROUNDS = {
    "H01": "Validate migrated values with an independent check (e.g. harness/oracle.py golden comparison), not only `verify`.",
    "H02": "None at input level; keep sub-µs precision out of scope or store as STRING via `override: STRING(MAX)`.",
    "H03": "Set `override: STRING(MAX)` on mixed INT/FLOAT properties holding large integers.",
    "H04": "Only use overrides that are lossless for the observed data; validate manually.",
    "H05": "Manually check uniqueness (`MATCH (n:L) WITH n.k AS k, count(*) AS c WHERE c>1 RETURN k`) and only use scalar PK columns.",
    "H06": "Normalise key types in Neo4j before export, or use the synthetic `_neo4j_id` PK.",
    "H07": "Replace NaN/Infinity inside lists in Neo4j before export.",
    "H08": "Use `column_renames` so same-named properties with different types get distinct names.",
    "H09": "Use `column_renames`/`override` so a shared rel-type property has one type across triplets, and avoid STRING props missing from some triplets.",
    "H10": "Query `WHERE 'Label' IN UNNEST(n.secondary_labels)` instead of `MATCH (n:Label)`.",
    "H11": "Use `table_renames` to shorten long edge table names (<= 120 chars).",
    "H12": "Use `column_renames` to keep destination PK column names <= 124 chars.",
    "H13": "Avoid backticks in labels/properties, or rename them.",
    "H14": "Do not use '~' as delimiter or inside --null-string.",
    "H15": "Only pass trusted, plain `gs://bucket/path` prefixes and simple graph names; always export GCS_PREFIX before running the runbook.",
    "H16": "Always export into a fresh --output-dir and a fresh GCS prefix.",
    "H17": "Re-run discovery immediately before export (quiesced DB).",
    "H18": "Do not use --sample-size for the final discovery.",
    "H19": "Interpret verify sample failures on such tables manually.",
    "H20": "Pass --sample-rows larger than the biggest table (verify then reads up to 5x rows).",
    "H21": "Delete the target database before re-running load_runbook.sh.",
    "H22": "Clamp/convert out-of-range dates in Neo4j before export.",
    "H23": "Split very wide labels before export.",
    "H24": "Run export under `timeout` and monitor progress.",
    "H25": "Do not run against an empty database.",
    "H26": "Edit schema_mapping.yaml carefully; re-run discovery to regenerate it.",
    "NEW-UX": "None needed for correctness; read the last traceback line.",
    "NEW-SIZE": "Check max property sizes in Neo4j before export (`size(n.prop) > 10*1024*1024`).",
    "NEW-MONO": "Review discovery_report.md manually for sequential business keys.",
    "NEW-DET": "Compare mappings semantically, not byte-wise.",
    "NEW-EMPTY": "Always check the 'Export complete' row counts.",
    "NEW-DIGITNAME": "Rename such properties/labels in Neo4j before export (column_renames does not change the graph property name).",
    "NEW-LABELCLASH": "Rename the label or relationship type in Neo4j before export.",
    "NEW-HANG": "Trim values > 2,621,440 chars (STRING) before export; add `invalidOutputPath=gs://...` to the runbook's Dataflow parameters.",
    "NEW-TAB": "Use a printable single-character delimiter such as '|' or ';'.",
    "NEW-UNESCAPE": "Do not use --emit-unescape; Dataflow already decodes the escapes (E-03 passed without it).",
    "NEW-EMPTYBYTES": "Post-load DML for known empty-bytes rows, or represent empty bytes differently in Neo4j.",
    "NEW-SILENTREJECT": "After each load, check `gcloud storage ls ${GCS_PREFIX}/invalid_records/` and run verify (counts catch the gap).",
    "NEW-INPUTMAP": "Pass label_priority via --label-priority; give every hand-written node entry its PK property (and a node entry for each pk_overrides label).",
    "NEW-DISCCRASH": "None at input level. Re-use a schema_mapping.yaml generated by an earlier version (used by this re-test for export/load/verify).",
    "NEW-YEARPAD": "None at input level; verify counts reveal the missing rows.",
    "NEW-VERIFYBYTES": "Ignore verify BYTES mismatches; validate BYTES with an independent check.",
    "NEW-VERIFYFLOAT": "Ignore int-vs-float mismatches in verify output.",
    "NEW-LABELRENAME": "Avoid table_renames on labels used by queries, or query the renamed label.",
    "NEW-NOEDGE": "`mkdir -p export_out/edges && touch` a placeholder, or add at least one relationship (used in R4).",
    "NEW-JOBNAME": "Start concurrent runbooks a few seconds apart (harness staggers by 3 s).",
}

NEW_TITLES = {
    "NEW-UX": "CLI surfaces operational/validation errors as raw Python tracebacks",
    "NEW-SIZE": "Values above Spanner limits (STRING 2,621,440 chars / 10 MiB) are not detected before load",
    "NEW-MONO": "Monotonic-PK hotspot warning depends on Neo4j scan order",
    "NEW-DET": "schema_mapping.yaml not byte-identical across Neo4j versions",
    "NEW-EMPTY": "An empty schema_mapping.yaml exports 0 rows with exit code 0",
    "NEW-DIGITNAME": "Original property/label names starting with a digit break CREATE PROPERTY GRAPH",
    "NEW-LABELCLASH": "Node label and relationship type with the same name produce conflicting LABEL definitions",
    "NEW-HANG": "A single rejected row makes the Dataflow load hang (no invalidOutputPath); oversized values not detected",
    "NEW-TAB": "Tab delimiter breaks the Dataflow load (campaign 2: silent corruption, columnDelimiter=9 treated as the character '9')",
    "NEW-UNESCAPE": "--emit-unescape generates invalid SQL (03_unescape.sql) and aborts the load",
    "NEW-EMPTYBYTES": "Empty BYTES values become NULL after load",
    "NEW-SILENTREJECT": "Rows rejected by Dataflow are written to invalid_records/ but the runbook still reports success",
    "NEW-INPUTMAP": "Partial --input-mapping files (renames / label_priority / pk_overrides) are rejected by load_mapping validation",
    "NEW-DISCCRASH": "discover crashes on every non-empty graph (UnboundLocalError: fixed_cols_lower, discovery.py:353)",
    "NEW-YEARPAD": "TIMESTAMP values with year < 1000 are serialized without zero padding and rejected by Spanner",
    "NEW-VERIFYBYTES": "verify reports false mismatches for all BYTES values and BYTES primary keys (no base64 decode)",
    "NEW-VERIFYFLOAT": "verify flags equal FLOAT64 values as mismatches when Neo4j stored them as integers",
    "NEW-LABELRENAME": "table_renames now also renames the graph LABEL, losing the original Neo4j label (verify queries fail)",
    "NEW-NOEDGE": "load_runbook.sh fails for graphs without relationships (missing edges/ directory)",
    "NEW-JOBNAME": "Dataflow job names collide when two loads start in the same second",
}

SEV_ORDER = {"P0": 0, "P1": 1, "P2": 2, None: 3}


def load(report_dir: Path) -> list[dict]:
    latest: "OrderedDict[str, dict]" = OrderedDict()
    for line in (report_dir / "findings.jsonl").read_text().splitlines():
        d = json.loads(line)
        latest.pop(d["test"], None)
        latest[d["test"]] = d
    return list(latest.values())


def build(report_dir: Path, severity_overrides: dict[str, str] | None = None) -> None:
    recs = load(report_dir)
    by_hyp: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        if r.get("hyp"):
            by_hyp[r["hyp"]].append(r)
    status: dict[str, str] = {}
    for h, rs in by_hyp.items():
        sts = {r["status"] for r in rs}
        if "Confirmed" in sts:
            status[h] = "Confirmed"
        elif "Refuted" in sts:
            status[h] = "Refuted"
        elif "Out of scope" in sts:
            status[h] = "Out of scope"
        elif "Not testable" in sts:
            status[h] = "Not testable"
        else:
            status[h] = "Observation"
    sev_over = severity_overrides or {}

    # ---------------- defects.md
    defects = []
    for h, rs in by_hyp.items():
        if status[h] != "Confirmed":
            continue
        conf = [r for r in rs if r["status"] == "Confirmed"]
        sev = sev_over.get(h) or min((r.get("severity") for r in conf), key=lambda s: SEV_ORDER.get(s, 3))
        title = HYP_TITLES.get(h) or NEW_TITLES.get(h) or conf[0].get("title") or h
        defects.append((SEV_ORDER.get(sev, 3), h, sev, title, conf))
    defects.sort(key=lambda x: (x[0], x[1]))
    lines = ["# Defect log", "", f"Run: `{report_dir.name}` · generated from `findings.jsonl` (latest record per test).", ""]
    lines += ["| DEF | Hypothesis | Severity | Title | Tests |", "| :--- | :--- | :--- | :--- | :--- |"]
    for i, (_, h, sev, title, conf) in enumerate(defects, 1):
        lines.append(f"| DEF-{i:03d} | {h} | {sev} | {title} | {', '.join(sorted({r['test'] for r in conf}))} |")
    lines.append("")
    for i, (_, h, sev, title, conf) in enumerate(defects, 1):
        lines += [f"### DEF-{i:03d} — {title}", "", f"- **Hypothesis:** {h} · **Severity:** {sev} · **Status:** Confirmed",
                  f"- **Tests:** {', '.join(sorted({r['test'] for r in conf}))}",
                  f"- **Workaround used / available:** {WORKAROUNDS.get(h, 'none known')}", "- **Evidence:**", ""]
        for r in conf[:4]:
            ev = r["evidence"].replace("```", "'''")
            lines += [f"  `{r['test']}`", "", "  ```text", "  " + ev[:1800].replace("\n", "\n  "), "  ```", ""]
    (report_dir / "defects.md").write_text("\n".join(lines) + "\n")

    # ---------------- summary.md
    defect_ids = {h: f"DEF-{i:03d}" for i, (_, h, *_rest) in enumerate(defects, 1)}
    s = ["# Robustness test summary", "", f"Run: `{report_dir.name}`", "", "## Hypothesis matrix", "",
         "| Hypothesis | Description | Status | Tests | Defect |", "| :--- | :--- | :--- | :--- | :--- |"]
    for h in list(HYP_TITLES) + sorted(k for k in by_hyp if k not in HYP_TITLES):
        rs = by_hyp.get(h, [])
        st = status.get(h, "NOT RUN")
        s.append(f"| {h} | {HYP_TITLES.get(h) or NEW_TITLES.get(h, '')} | **{st}** | {', '.join(sorted({r['test'] for r in rs}))} | {defect_ids.get(h, '—')} |")
    s += ["", "## All test records (latest per test)", "", "| Test | Hyp | Status | Evidence (truncated) |", "| :--- | :--- | :--- | :--- |"]
    for r in sorted(recs, key=lambda r: r["test"]):
        ev = r["evidence"].replace("|", "\\|").replace("\n", " ")[:220]
        s.append(f"| {r['test']} | {r.get('hyp') or ''} | {r['status']} | {ev} |")
    counts = defaultdict(int)
    for r in recs:
        counts[r["status"]] += 1
    s[4:4] = [f"Records: {dict(counts)} · Hypotheses: " + ", ".join(f"{k}={sum(1 for v in status.values() if v == k)}" for k in ["Confirmed", "Refuted", "Not testable", "Out of scope", "Observation"]), ""]
    (report_dir / "summary.md").write_text("\n".join(s) + "\n")


if __name__ == "__main__":
    build(Path(sys.argv[1]))


def _hyp_status(recs: list[dict]) -> dict[str, tuple[str, list[dict]]]:
    by: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        if r.get("hyp"):
            by[r["hyp"]].append(r)
    out = {}
    for h, rs in by.items():
        sts = {r["status"] for r in rs}
        st = ("Confirmed" if "Confirmed" in sts else "Refuted" if "Refuted" in sts else
              "Out of scope" if "Out of scope" in sts else "Not testable" if "Not testable" in sts else "Observation")
        out[h] = (st, rs)
    return out


def build_retest(prev_dir: Path, cur_dir: Path, out_name: str = "retest.md") -> None:
    """Write cur_dir/retest.md comparing defect status between two campaigns."""
    import re as _re

    prev_defs = {}
    for line in (prev_dir / "defects.md").read_text().splitlines():
        m = _re.match(r"^\| (DEF-\d+) \| (\S+) \| (P\d) \| (.+?) \| (.+?) \|$", line)
        if m:
            prev_defs[m.group(2)] = (m.group(1), m.group(3), m.group(4))
    prev = _hyp_status(load(prev_dir))
    cur = _hyp_status(load(cur_dir))
    rows, counts = [], defaultdict(int)
    for h, (def_id, sev, title) in sorted(prev_defs.items(), key=lambda kv: kv[1][0]):
        st, rs = cur.get(h, ("NOT RUN", []))
        verdict = {"Refuted": "Fixed", "Confirmed": "Still open"}.get(st, "Not re-tested")
        counts[verdict] += 1
        ev = ""
        pick = [r for r in rs if r["status"] == ("Confirmed" if st == "Confirmed" else "Refuted")]
        if pick:
            ev = pick[-1]["evidence"].replace("|", "\\|").replace("\n", " ")[:260]
        rows.append(f"| {def_id} | {h} | {sev} | {title} | **{verdict}** | {', '.join(sorted({r['test'] for r in rs}))} | {ev} |")
    new = [(h, v) for h, v in cur.items() if h not in prev_defs and v[0] == "Confirmed"]
    lines = ["# Re-test report", "",
             f"Previous campaign: `{prev_dir.name}` · Re-test campaign: `{cur_dir.name}`", "",
             "Verdicts: " + ", ".join(f"**{k}** = {v}" for k, v in sorted(counts.items())) + f" · New defects: **{len(new)}**", "",
             "## Campaign-1 defects", "",
             "| DEF | Hypothesis | Sev | Title | Verdict | Re-test tests | Evidence (re-test) |",
             "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |", *rows, ""]
    blocked = sorted({r["test"].split(":", 1)[1] for r in load(cur_dir) if r["test"].startswith("BLOCKED:")})
    lines += ["## Tests blocked by NEW-DISCCRASH", "",
              (", ".join(f"`{b}`" for b in blocked) if blocked else "None."), ""]
    lines += ["## New defects found in the re-test", ""]
    if new:
        lines += ["| Hypothesis | Title | Tests | Evidence |", "| :--- | :--- | :--- | :--- |"]
        for h, (st, rs) in sorted(new):
            conf = [r for r in rs if r["status"] == "Confirmed"]
            title = HYP_TITLES.get(h) or NEW_TITLES.get(h) or conf[-1].get("title") or h
            tl = sorted({r['test'] for r in conf})
            tests = ", ".join(tl[:4]) + (f" (+{len(tl) - 4} more)" if len(tl) > 4 else "")
            lines.append(f"| {h} | {title} | {tests} | "
                         f"{conf[-1]['evidence'].replace('|', chr(92) + '|').replace(chr(10), ' ')[:300]} |")
    else:
        lines.append("None.")
    (cur_dir / out_name).write_text("\n".join(lines) + "\n")
