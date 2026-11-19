"""T3 (full E2E load) + T4 (verify mutation testing).

Runs R1..R4 (+ rb_r1_02 with --emit-unescape, + G-02 negative) in parallel. Each run gets its own
ephemeral Neo4j 5.x container so export, load, verify and mutations can proceed concurrently while
Neo4j keeps that run's data (required by `verify`).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from neo4j import GraphDatabase
import pytest

from fixtures import golden_r2
from fixtures import graphs as g
from harness import neo4j_util as nu
from harness import oracle
from harness import runbook as rb
from harness import spanner_ddl as sd
from harness import tool
from harness.findings import check, record

from neo4j_spanner_export.config import NodeTableMapping, SchemaMapping

pytestmark = pytest.mark.timeout(10800)

PW = "testpassword123"
_SFX = os.environ.get("RB_T3_CONTAINER_SUFFIX", "")
_PORT_BASE = 7700 if not _SFX else 7710
RUN_PORTS = {"r1": _PORT_BASE + 1, "r2": _PORT_BASE + 2, "r3": _PORT_BASE + 3, "r4": _PORT_BASE + 4, "r5": _PORT_BASE + 5}
ALL_RUNS = ["r1", "r2", "r3", "r4", "r5"]


@dataclass
class Run:
    name: str
    uri: str
    driver: Any
    db_id: str
    work: Path
    bundle: Any = None
    load: Any = None
    verify: dict = field(default_factory=dict)
    error: str | None = None
    extra: dict = field(default_factory=dict)


def _container(name: str, port: int) -> str:
    cname = f"neo4j-rb{_SFX}-{name}"
    nu.ensure_container(cname, port, "v5", PW, heap="1G")
    return f"bolt://localhost:{port}"


def _r1_mapping() -> SchemaMapping:
    inm = SchemaMapping(label_priority=["Product", "Category", "Service", "Account", "Order", "AuditNote"],
                        table_renames={"Order": "Orders"}, pk_overrides={"Order": ["tenant_id", "order_id"]})
    inm.nodes["Product"] = NodeTableMapping(raw_label="Product", spanner_table="Product", pk_columns=["sku"],
                                            pk_source="uniqueness_constraint", column_renames={"order": "order_num"})
    return inm


def run_verify(run: Run, gcp, sample_rows: int = 100_000, seed: int = 42, graph: str | None = None,
               queries_file: Path | None = None, tag: str = "base") -> dict:
    rep = run.work / f"verify_{tag}.json"
    args = ["verify", "--uri", run.uri, "--mapping", str(run.bundle.mapping_path), "--project", gcp.project,
            "--instance", gcp.instance, "--database", run.db_id, "--graph", graph or f"Rb{run.name.upper()}",
            "--sample-rows", str(sample_rows), "--seed", str(seed), "--output-report", str(rep)]
    if queries_file:
        args += ["--queries-file", str(queries_file)]
    p = tool.cli(args, env={"NEO4J_PASSWORD": PW}, timeout=3600)
    out = {"rc": p.returncode, "stdout": p.stdout[-3000:], "stderr": p.stderr[-3000:], "traceback": tool.has_traceback(p.stderr)}
    if rep.exists():
        out["report"] = json.loads(rep.read_text())
    return out


def _manual_mapping(name: str):
    """Hand-built mappings for R4/R5 while discovery is blocked (NEW-DISCCRASH)."""
    from harness import mapping_builder as mb

    if name == "r4":
        return mb.mapping([mb.node("Frag", ["fr_id"], {"fr_id": "STRING(MAX)", "fl_val": "ARRAY<FLOAT64>"})])
    a = mb.node("Rj", ["rj_id"], {"rj_id": "STRING(MAX)", "rj_val": "STRING(MAX)"})
    return mb.mapping([a], [mb.edge(a, "RJ_REL", a)])


def _previous_mapping(name: str):
    from neo4j_spanner_export.config import load_mapping

    m = load_mapping(Path(os.environ["RB_MAPPING_SOURCE"]) / f"t3_{name}" / "schema_mapping.yaml")
    if name == "r2":
        m.nodes["TConf"].properties["c_if"].override = "STRING(MAX)"  # ints > 2^53 (new widening rule)
    return m


def _export_with(drv, w: Path, name: str, **kw):
    """discover+export normally; with RB_MAPPING_SOURCE (discovery blocked) export a previous/hand-built mapping."""
    if not os.environ.get("RB_MAPPING_SOURCE"):
        inm = kw.pop("input_mapping", None)
        return tool.discover_and_export(drv, w, input_mapping=inm, **kw)
    kw.pop("input_mapping", None)
    from neo4j_spanner_export.config import save_mapping

    m = _previous_mapping(name) if name in ("r1", "r2", "r3") else _manual_mapping(name)
    w.mkdir(parents=True, exist_ok=True)
    save_mapping(m, w / "schema_mapping.yaml")
    return tool.export(drv, w, m, **kw)


def _prepare(name: str, gcp, work_root: Path) -> Run:
    uri = _container(name, RUN_PORTS[name])
    drv = GraphDatabase.driver(uri, auth=("neo4j", PW))
    nu.wait_ready(drv)
    w = work_root / f"t3_{name}"
    w.mkdir(parents=True, exist_ok=True)
    run = Run(name, uri, drv, f"rb_{name}_01", w)
    prefix = gcp.prefix(name)
    graph = f"Rb{name.upper()}"
    if name == "r1":
        from scripts.seed_synthetic_graph import seed_graph

        nu.wipe(drv)
        seed_graph(uri, "neo4j", PW, "neo4j", include_ambiguous=False)
        run.bundle = _export_with(drv, w, "r1", input_mapping=_r1_mapping(), gcs_prefix=prefix, graph_name=graph, chunk_rows=1)
    elif name == "r2":
        g.seed_r2(drv)
        run.bundle = _export_with(drv, w, "r2", input_mapping=g.r2_input_mapping(),
                                  gcs_prefix=prefix, graph_name=graph, delimiter="|")
    elif name == "r3":
        g.seed_g5_topology(drv)
        run.bundle = _export_with(drv, w, "r3", input_mapping=SchemaMapping(label_priority=g.G5_LABEL_PRIORITY),
                                  gcs_prefix=prefix, graph_name=graph,
                                              delimiter=os.environ.get("RB_R3_DELIM", "\\t"))
    elif name == "r4":
        # Step 1: NaN/Infinity list values must be rejected at export (H07 fix) instead of emitting invalid JSON.
        g.seed_r4_fragile(drv)
        wf = w / "fragile"
        wf.mkdir(exist_ok=True)
        try:
            _export_with(drv, wf, "r4", gcs_prefix=prefix, graph_name=graph)
            run.extra["fragile_export"] = ("accepted", (wf / "export_out" / "nodes").exists())
        except Exception as e:  # noqa: BLE001
            run.extra["fragile_export"] = ("rejected", f"{type(e).__name__}: {str(e)[:300]}")
        # Step 2 (D16): load the remaining nodes-only graph -> end-to-end re-test of NEW-NOEDGE.
        g.seed_r4_nodes_only(drv)
        run.bundle = _export_with(drv, w, "r4", gcs_prefix=prefix, graph_name=graph)
    elif name == "r5":
        g.seed_r5_reject_probe(drv)
        try:
            run.bundle = _export_with(drv, w, "r5", gcs_prefix=prefix, graph_name=graph)
        except Exception as e:  # noqa: BLE001
            run.extra["export_rejected"] = f"{type(e).__name__}: {str(e)[:300]}"
    return run


@pytest.fixture(scope="module")
def e2e(gcp, work_root):
    runs: dict[str, Run] = {}
    extra: dict[str, Any] = {}
    selected = os.environ.get("RB_T3_RUNS", "r1,r2,r3,r4,r5,r1u,g02").split(",")
    needed = {n for n in ALL_RUNS if n in selected}
    if "r1u" in selected:
        needed.add("r1")
    if "g02" in selected:
        needed.add("r4")
    with ThreadPoolExecutor(max_workers=5) as pool:
        for r in pool.map(lambda n: _prepare(n, gcp, work_root), sorted(needed)):
            runs[r.name] = r
    for n in ALL_RUNS:
        if n not in runs:
            runs[n] = Run(n, "", None, f"rb_{n}_01", work_root / f"t3_{n}", load=rb.RunbookResult(-2, Path("/dev/null"), 0.0, [], []))
    b12 = bg = None
    if "r1u" in selected:
        # rb_r1_02: same R1 data, --emit-unescape (E-03 double-decode check)
        r1 = runs["r1"]
        w12 = work_root / "t3_r1_unescape"
        w12.mkdir(exist_ok=True)
        b12 = tool.export(r1.driver, w12, r1.bundle.mapping, gcs_prefix=gcp.prefix("r1u"), graph_name="RbR1U", emit_unescape=True)
    if "g02" in selected:
        # G-02 negative: tiny R4 bundle, public IPs (org policy blocks)
        wg = work_root / "t3_g02"
        wg.mkdir(exist_ok=True)
        bg = tool.export(runs["r4"].driver, wg, runs["r4"].bundle.mapping, gcs_prefix=gcp.prefix("g02"), graph_name="RbG02")

    def _load(item):
        i, (key, out, db, prefix, pub) = item
        time.sleep(3 * i + (30 if _SFX else 0))  # harness workaround for NEW-JOBNAME (job names only unique per second)
        db_obj = gcp.database(db)
        if key in selected and db_obj.exists():
            db_obj.drop()  # harness workaround for H21 (runbook cannot re-run into an existing DB)
        if key not in selected:
            prev = _load_previous(work_root, key)
            if prev is not None:
                return key, prev
            return key, rb.RunbookResult(-2, Path("/dev/null"), 0.0, [], [])  # not selected in this session
        tmo = 2400 if key == "r5" else 7200
        res = rb.run(out, gcp, db, prefix, disable_public_ips=not pub, timeout=tmo)
        if res.rc == -999:  # harness timeout -> cancel whatever Dataflow job is still running
            rb.cancel_jobs(gcp, res.job_ids)
        return key, res

    jobs = [(n, r.bundle.out_dir, r.db_id, gcp.prefix(n), False) for n, r in runs.items() if n in selected and r.bundle is not None]
    if b12 is not None:
        jobs.append(("r1u", b12.out_dir, "rb_r1_02", gcp.prefix("r1u"), False))
    if bg is not None:
        jobs.append(("g02", bg.out_dir, "rb_g02_01", gcp.prefix("g02"), True))
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        loads = dict(pool.map(_load, enumerate(jobs)))
    for k, ld in loads.items():
        (work_root / f"load_{k}.json").write_text(json.dumps({"rc": ld.rc, "log": str(ld.log_path), "elapsed": ld.elapsed_s,
                                                              "jobs": ld.job_ids, "stages": ld.stages}))
    unsel = rb.RunbookResult(-2, Path("/dev/null"), 0.0, [], [])
    for n, r in runs.items():
        r.load = loads.get(n, unsel)
    extra["r1u"] = (b12, loads.get("r1u", unsel))
    extra["g02"] = (bg, loads.get("g02", unsel))
    # baseline verify (parallel)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {n: pool.submit(run_verify, r, gcp) for n, r in runs.items() if r.load.rc == 0 and r.bundle is not None}
        for n, f in futs.items():
            runs[n].verify = f.result()
    (work_root / "t3_summary.json").write_text(json.dumps({
        n: {"rc": r.load.rc, "elapsed": r.load.elapsed_s, "jobs": r.load.job_ids, "stages": r.load.stages,
            "verify_rc": r.verify.get("rc")} for n, r in runs.items()}, indent=2))
    yield runs, extra
    for r in runs.values():
        if r.driver is not None:
            r.driver.close()
    for n in needed:
        subprocess.run(["podman", "rm", "-f", f"neo4j-rb{_SFX}-{n}"], capture_output=True)


def _load_previous(work_root: Path, key: str):
    f = work_root / f"load_{key}.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text())
    return rb.RunbookResult(d["rc"], Path(d["log"]), d["elapsed"], d["jobs"], d["stages"])


def _db(gcp, run: Run):
    return gcp.database(run.db_id)


def _q(gcp, run):
    db = _db(gcp, run)
    return lambda sql: sd.query(db, sql)


def _skip_unselected(ld) -> None:
    if ld.rc == -2:
        pytest.skip("run not selected in this session (RB_T3_RUNS)")


def _stage_failure(load) -> str:
    return f"rc={load.rc}; stages reached={load.stages}; log tail:\n" + load.log[-2500:]


# ============================================================================ T3: loads

@pytest.mark.t3
@pytest.mark.parametrize("name", ["r1", "r2", "r3"])
def test_G01_runbook_loads(e2e, name, gcp):
    runs, _ = e2e
    ld = runs[name].load
    _skip_unselected(ld)
    errs = ""
    if ld.rc != 0 and ld.job_ids:
        errs = rb.job_error(gcp, ld.job_ids[-1])
    check(ld.rc == 0, None, f"G-01[{name}]", f"elapsed={ld.elapsed_s:.0f}s jobs={ld.job_ids} " + ("" if ld.rc == 0 else _stage_failure(ld) + errs),
          severity="P0", title="Runbook load failed")


@pytest.mark.t3
def test_D08_R4_fragile_values_load(e2e, gcp):
    runs, _ = e2e
    r4 = runs["r4"]
    _skip_unselected(r4.load)
    fr = r4.extra.get("fragile_export", ("n/a", ""))
    check(fr[0] == "rejected" and ("NaN" in fr[1] or "Infinity" in fr[1] or "RFC8259" in fr[1]), "H07", "D-08(T3)/G-04",
          f"export of [1.5,NaN]/[Infinity,2.0] list values: {fr}", severity="P1",
          title="NaN/Infinity inside lists serialized as invalid JSON")


@pytest.mark.t3
def test_NEW_NOEDGE_nodes_only_load(e2e, gcp):
    runs, _ = e2e
    ld = runs["r4"].load
    _skip_unselected(ld)
    rows = None
    if ld.rc == 0:
        rows = sd.query(_db(gcp, runs["r4"]), "SELECT COUNT(*) AS c FROM Frag")[0]["c"]
    check(ld.rc == 0 and rows == 2, "NEW-NOEDGE", "G-10(T3:nodes-only)",
          f"nodes-only graph (no relationships): runbook rc={ld.rc}, Frag rows={rows}, stages={ld.stages}" + ("" if ld.rc == 0 else "\n" + ld.log[-1200:]),
          severity="P1", title="load_runbook.sh fails for graphs without relationships (missing edges/ directory)")


@pytest.mark.t3
def test_NEW_TAB_tab_delimiter_load(e2e, gcp):
    runs, _ = e2e
    r3 = runs["r3"]
    _skip_unselected(r3.load)
    delim = os.environ.get("RB_R3_DELIM", "\\t")
    if delim not in ("\\t", "\t"):
        pytest.skip("R3 not run with tab delimiter")
    err = rb.job_error(gcp, r3.load.job_ids[0]) if r3.load.rc != 0 and r3.load.job_ids else ""
    counts = {}
    if r3.load.rc == 0:
        for t in ("Person", "Company", "Event", "Person__KNOWS__Person"):
            counts[t] = sd.query(_db(gcp, r3), f"SELECT COUNT(*) AS c FROM {t}")[0]["c"]
        bad_keys = sd.query(_db(gcp, r3), "SELECT COUNT(*) AS c FROM Person WHERE STRPOS(pid, CODE_POINTS_TO_STRING([9])) > 0")[0]["c"]
        counts["Person keys containing TAB"] = bad_keys
    exp = {"Person": 2000, "Company": 50, "Event": 60000, "Person__KNOWS__Person": 6053, "Person keys containing TAB": 0}
    check(r3.load.rc == 0 and counts == exp, "NEW-TAB", "E-06(T3:r3)",
          f"R3 exported with --delimiter '\\t': runbook rc={r3.load.rc}; Spanner counts={counts} expected={exp}; {err[:400]}",
          severity="P1", title="Tab delimiter is accepted by export but breaks the Dataflow load")


@pytest.mark.t3
def test_NEW_HANG_rejected_row_probe(e2e, gcp):
    runs, _ = e2e
    r5 = runs["r5"]
    if r5.load.rc == -2 and "export_rejected" not in r5.extra:
        pytest.skip("R5 not selected")
    if "export_rejected" in r5.extra:
        check(True, "NEW-HANG", "E-07(T3:r5)", f"10.4 MB (2.6M emoji) value rejected at export: {r5.extra['export_rejected']}")
        return
    ld = r5.load
    rows = sd.query(_db(gcp, r5), "SELECT COUNT(*) AS c FROM Rj")[0]["c"] if ld.stages else None
    inv = subprocess.run(["gcloud", "storage", "ls", "--recursive", gcp.prefix("r5") + "/invalid_records/"], capture_output=True, text=True)
    inv_objs = [l for l in inv.stdout.splitlines() if l.startswith("gs://") and not l.endswith(":")]
    hung = ld.rc == -999
    silent = ld.rc == 0 and rows is not None and rows < 2
    check(not hung, "NEW-HANG", "E-07(T3:r5)",
          f"value of 2,600,000 4-byte chars (10.4 MB): runbook rc={ld.rc} elapsed={ld.elapsed_s:.0f}s, Rj rows in Spanner={rows}/2, "
          f"invalid_records objects={len(inv_objs)}", severity="P1",
          title="A single rejected row makes the Dataflow load hang (no invalidOutputPath)")
    check(not silent, "NEW-SILENTREJECT", "E-07(T3:r5,silent)",
          f"runbook rc={ld.rc} ('Load complete!'={'Load complete!' in ld.log}) although only {rows}/2 Rj rows loaded; "
          f"rejected rows only visible under {gcp.prefix('r5')}/invalid_records/ ({inv_objs[:2]}); exporter did not flag the 10.4 MB value "
          f"(checks characters, not bytes)", severity="P1",
          title="Rows rejected by Dataflow are written to invalid_records/ but the runbook still reports success")


@pytest.mark.t3
def test_G02_public_ip_negative(e2e, gcp):
    _, extra = e2e
    _, ld = extra["g02"]
    _skip_unselected(ld)
    err = rb.job_error(gcp, ld.job_ids[0]) if ld.job_ids else ""
    ok = ld.rc != 0 and ld.elapsed_s < 3600
    check(ok, None, "G-02", f"rc={ld.rc} elapsed={ld.elapsed_s:.0f}s stages={ld.stages}; dataflow error: {err[:600]}", severity="P2")
    try:
        _db(gcp, Run("g02", "", None, "rb_g02_01", Path("."))).drop()
    except Exception:  # noqa: BLE001
        pass


# ============================================================================ T3: R2 golden oracle

@pytest.fixture(scope="module")
def r2_diffs(e2e, gcp):
    runs, _ = e2e
    r2 = runs["r2"]
    if r2.load.rc != 0:
        pytest.skip("R2 load failed")
    tostr = {"VTime": {}, "VDur": {}}
    for lbl, col in [("VTime", "t_val"), ("VDur", "du_val")]:
        for row in nu.run(r2.driver, f"MATCH (n:{lbl}) RETURN n.case_id AS c, toString(n.{col}) AS s"):
            tostr[lbl][row["c"]] = row["s"]
    inst = {r["c"]: oracle.ts(r["s"], r["ns"]) for r in nu.run(
        r2.driver, "MATCH (n:VDateTime) RETURN n.case_id AS c, n.dt_val.epochSeconds AS s, n.dt_val.nanosecond AS ns")}
    mapping = oracle.load_mapping_yaml(r2.bundle.mapping_path)
    cif = mapping["nodes"]["TConf"]["properties"]["c_if"]
    exp = golden_r2.expected_r2(tostr, inst, c_if_type=cif.get("override") or cif["resolved"])
    diffs = []
    for label, spec in exp.items():
        diffs += oracle.compare_table(_q(gcp, r2), mapping, label, spec["key"], spec["rows"])
    for et, cnt in golden_r2.EXPECTED_EDGE_COUNTS_R2.items():
        tbl = mapping["edges"][et]["spanner_table"]
        n = sd.query(_db(gcp, r2), f"SELECT COUNT(*) AS c FROM {tbl}")[0]["c"]
        if n != cnt:
            diffs.append({"table": et, "error": f"edge count {n} != {cnt}"})
    (r2.work / "golden_diffs.json").write_text(json.dumps(diffs, indent=2, default=str))
    return diffs


def _diffs_for(diffs, table, keys=None, col=None):
    out = []
    for d in diffs:
        if d.get("table") != table:
            continue
        if keys is not None and not any(f"'{k}'" in d.get("key", "") for k in keys):
            continue
        if col is not None and d.get("column") != col:
            continue
        out.append(d)
    return out


GOLDEN_CHECKS = [
    # (test_id, hyp, severity, table, case keys or None, title)
    ("E-01", None, "P0", "VStr", ["empty", "space", "absent", "null_like_suffix", "quoted_null"], "NULL vs empty vs space"),
    ("E-03", None, "P0", "VStr", ["literal_backslash_n", "real_lf", "crlf", "lone_cr", "trailing_backslash", "double_backslash",
                                  "backslash_quote", "quote_edges", "delim_edges", "tab", "unicode_escape_text"], "escape matrix"),
    ("E-04", None, "P1", "VStr", ["nul", "line_sep", "bom_start", "rtl", "emoji4", "cjk"], "unicode edge cases"),
    ("E-07", None, "P2", "VStr", ["one_mib", "near_char_limit"], "large strings"),
    ("D-04", None, "P1", "VInt", None, "INT64 boundaries"),
    ("D-06", None, "P1", "VFloat", ["neg_zero", "subnormal", "max", "tenth", "tiny", "pi"], "FLOAT64 bit-exact"),
    ("D-07", None, "P1", "VFloat", ["nan", "pinf", "ninf"], "scalar NaN/Infinity"),
    ("D-19", "NEW-EMPTYBYTES", "P2", "VBytes", None, "Empty BYTES values become NULL after load"),
    ("D-14", "H02", "P0", "VDateTime", ["utc_ns", "max"], "DateTime nanoseconds truncated to microseconds on export"),
    ("D-16", None, "P1", "VDateTime", ["berlin_gap", "berlin_overlap", "plus14", "minus12", "epoch", "pre_epoch_us", "min"], "time zones / DST / range"),
    ("A-10", None, "P1", "VLocalDT", None, "LocalDateTime with default timezone"),
    ("D-17", None, "P2", "VTime", None, "TIME -> STRING ISO text"),
    ("D-17", None, "P2", "VDur", None, "DURATION -> STRING ISO text"),
    ("D-18", None, "P2", "VPoint", None, "POINT -> JSON"),
    ("D-12", None, "P1", "VListStr", None, "ARRAY<STRING> incl. specials, empty, 100k elements"),
    ("D-13", "H03", "P0", "VListInt", None, "ARRAY<INT64> exactness (> 2^53)"),
    ("D-12", None, "P1", "VListFloat", None, "ARRAY<FLOAT64>"),
    ("D-12", None, "P1", "VListBool", None, "ARRAY<BOOL>"),
    ("D-12", None, "P1", "VListTemporal", None, "list of temporals -> JSON"),
    ("D-05", "H03", "P0", "TConf", None, "INT64/FLOAT64 widening silently loses integer precision > 2^53"),
    ("B-10", None, "P0", "PkTs", None, "TIMESTAMP PK override"),
    ("B-10", None, "P0", "PkFloat", None, "FLOAT64 PK override"),
    ("B-10", None, "P0", "PkBytes", None, "BYTES PK override"),
    ("F-02", None, "P0", "PkComp", None, "composite PK override"),
    ("F-02", None, "P0", "PkNone", None, "synthetic PK"),
    ("D-09", None, "P2", "PkWide", None, "INT/STRING widened PK"),
]


@pytest.mark.t3
@pytest.mark.parametrize("tid,hyp,sev,table,keys,title", GOLDEN_CHECKS, ids=[f"{c[0]}-{c[3]}" for c in GOLDEN_CHECKS])
def test_R2_golden(r2_diffs, tid, hyp, sev, table, keys, title):
    ds = _diffs_for(r2_diffs, table, keys)
    check(not ds, hyp, f"{tid}(T3:{table})", json.dumps(ds, default=str)[:2500], severity=sev, title=title)


@pytest.mark.t3
def test_R2_edges(r2_diffs):
    ds = [d for d in r2_diffs if "edge count" in d.get("error", "")]
    check(not ds, None, "F-10/B-10(edges)", json.dumps(ds), severity="P0")


# ============================================================================ T3: R1 / R3 independent converter

def _independent_compare(run: Run, gcp, max_rows: int = 3000) -> list[dict]:
    mapping = oracle.load_mapping_yaml(run.bundle.mapping_path)
    diffs: list[dict] = []
    for label, nm in mapping["nodes"].items():
        if nm["is_synthetic_pk"]:
            continue
        props = nm["properties"]
        excl = nm.get("excluded_labels") or []
        where = ("WHERE NOT (" + " OR ".join(f"n:`{x}`" for x in excl) + ")") if excl else ""
        recs = nu.run(run.driver, f"MATCH (n:`{label}`) {where} RETURN properties(n) AS p, labels(n) AS l LIMIT {max_rows}")
        cols = {raw: p["spanner_column"] for raw, p in props.items()}
        key_raw = nm["pk_columns"]
        rows = sd.query(_db(gcp, run), f"SELECT {', '.join(cols.values())} FROM {nm['spanner_table']}")
        by_key = {tuple(oracle.norm_spanner(r[cols[k]]) for k in key_raw): r for r in rows}
        for rec in recs:
            p = rec["p"]
            key = tuple(oracle.expected_from_neo4j(p.get(k), props[k].get("override") or props[k]["resolved"]) for k in key_raw)
            srow = by_key.get(key)
            if srow is None:
                diffs.append({"table": label, "key": repr(key), "error": "missing_in_spanner"})
                continue
            for raw, pm in props.items():
                typ = pm.get("override") or pm["resolved"]
                if raw == "secondary_labels" and nm["has_secondary_labels"]:
                    ev = sorted(x for x in rec["l"] if x != label)
                else:
                    ev = oracle.expected_from_neo4j(p.get(raw), typ)
                av = oracle.norm_spanner(srow[cols[raw]])
                if not oracle.values_equal(av, ev):
                    diffs.append({"table": label, "key": repr(key)[:80], "column": raw, "expected": repr(ev)[:150], "actual": repr(av)[:150]})
    # counts for every node/edge table, via independent Cypher
    for label, nm in mapping["nodes"].items():
        excl = nm.get("excluded_labels") or []
        where = ("WHERE NOT (" + " OR ".join(f"n:`{x}`" for x in excl) + ")") if excl else ""
        n4 = nu.run(run.driver, f"MATCH (n:`{label}`) {where} RETURN count(n) AS c")[0]["c"]
        sp = sd.query(_db(gcp, run), f"SELECT COUNT(*) AS c FROM {nm['spanner_table']}")[0]["c"]
        if n4 != sp:
            diffs.append({"table": label, "error": f"count neo4j={n4} spanner={sp}"})
    total_e = nu.run(run.driver, "MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
    sp_e = sum(sd.query(_db(gcp, run), f"SELECT COUNT(*) AS c FROM {em['spanner_table']}")[0]["c"] for em in mapping["edges"].values())
    if total_e != sp_e:
        diffs.append({"table": "*edges*", "error": f"total edges neo4j={total_e} spanner={sp_e}"})
    return diffs


@pytest.mark.t3
@pytest.mark.parametrize("name", ["r1", "r3"])
def test_R1_R3_independent_oracle(e2e, gcp, name):
    runs, _ = e2e
    r = runs[name]
    if r.load.rc != 0:
        pytest.skip("load failed")
    diffs = _independent_compare(r, gcp)
    (r.work / "oracle_diffs.json").write_text(json.dumps(diffs, indent=2))
    tid = "E-06/E-08/B-16" if name == "r3" else "E-08/C-05"  # noqa: F841
    nonts = diffs
    check(not nonts, None, f"{tid}(T3:{name})", json.dumps(diffs[:15]), severity="P1",
          title=f"{name.upper()} differs from independent oracle")


@pytest.mark.t3
def test_E03_emit_unescape_double_decode(e2e, gcp):
    runs, extra = e2e
    b12, ld = extra["r1u"]
    _skip_unselected(ld)
    if ld.rc != 0:
        check(False, "NEW-UNESCAPE", "E-03(unescape)", _stage_failure(ld), severity="P1",
              title="--emit-unescape generates invalid SQL (03_unescape.sql) and aborts the load")
    db = gcp.database("rb_r1_02")
    src = {r["k"]: r["t"] for r in nu.run(runs["r1"].driver, "MATCH (p:Product) RETURN p.sku AS k, p.title AS t")}
    src.update({"note": nu.run(runs["r1"].driver, "MATCH (n:AuditNote) RETURN n.note AS t")[0]["t"]})
    got = {r["sku"]: r["title"] for r in sd.query(db, "SELECT sku, title FROM Product")}
    got["note"] = sd.query(db, "SELECT note FROM AuditNote")[0]["note"]
    bad = {k: (src[k], got.get(k)) for k in src if src[k] != got.get(k)}
    check(not bad, "NEW-UNESCAPE", "E-03(unescape)", f"load with --emit-unescape succeeded (rc=0); strings after 03_unescape.sql: mismatches={bad}",
          severity="P1", title="--emit-unescape generates invalid SQL / double-decodes strings")


@pytest.mark.t3
def test_F09_secondary_label_gql_semantics(e2e, gcp):
    runs, _ = e2e
    r = runs["r3"]
    if r.load.rc != 0:
        pytest.skip("load failed")
    cy = nu.run(r.driver, "MATCH (n:Employee) RETURN count(n) AS c")[0]["c"]
    try:
        gq = sd.query(_db(gcp, r), "GRAPH RbR3 MATCH (n:Employee) RETURN COUNT(*) AS c")[0]["c"]
    except Exception as e:  # noqa: BLE001
        gq = f"ERROR {str(e)[:200]}"
    alt = sd.query(_db(gcp, r), "GRAPH RbR3 MATCH (n:Person) WHERE 'Employee' IN UNNEST(n.secondary_labels) RETURN COUNT(*) AS c")[0]["c"]
    check(gq == cy, "H10", "F-09", f"Cypher MATCH (n:Employee) -> {cy}; GQL MATCH (n:Employee) -> {gq}; workaround via secondary_labels -> {alt}",
          severity="P1", title="Secondary labels are not queryable as GQL labels")


@pytest.mark.t3
def test_C05_C11_F10_gql_queries(e2e, gcp):
    runs, _ = e2e
    res = {}
    r1, r3 = runs["r1"], runs["r3"]
    qs = [
        (r1, "vip_label", "MATCH (n:`VIP - Customer`) RETURN count(n) AS c", "GRAPH RbR1 MATCH (n:`VIP - Customer`) RETURN COUNT(*) AS c"),
        (r3, "reverse_traversal", "MATCH (p:Person)-[:WORKS_AT]->(c:Company {cid:'C007'}) RETURN count(p) AS c",
         "GRAPH RbR3 MATCH (c:Company {cid:'C007'})<-[:WORKS_AT]-(p:Person) RETURN COUNT(*) AS c"),
        (r3, "likes_all_triplets", "MATCH ()-[r:LIKES]->() RETURN count(r) AS c", "GRAPH RbR3 MATCH ()-[r:LIKES]->() RETURN COUNT(*) AS c"),
        (r3, "parallel_follows", "MATCH ()-[r:FOLLOWS]->() RETURN count(r) AS c", "GRAPH RbR3 MATCH ()-[r:FOLLOWS]->() RETURN COUNT(*) AS c"),
        (r3, "self_loops", "MATCH (a)-[r:KNOWS]->(a) RETURN count(r) AS c", "GRAPH RbR3 MATCH (a)-[r:KNOWS]->(b) WHERE a = b RETURN COUNT(*) AS c"),
        (r3, "two_hop", "MATCH (a:Person {pid:'P00001'})-[:KNOWS]->()-[:KNOWS]->(c) RETURN count(c) AS c",
         "GRAPH RbR3 MATCH TRAIL (a:Person {pid:'P00001'})-[:KNOWS]->()-[:KNOWS]->(c) RETURN COUNT(*) AS c"),  # TRAIL = Cypher rel-uniqueness
        (r3, "hub_degree", "MATCH (:Hub)-[r:LINKS]->() RETURN count(r) AS c", "GRAPH RbR3 MATCH (:Hub)-[r:LINKS]->() RETURN COUNT(*) AS c"),
    ]
    for run, name, cy, gq in qs:
        if run.load.rc == -2:
            continue
        if run.load.rc != 0:
            res[name] = "load failed"
            continue
        a = nu.run(run.driver, cy)[0]["c"]
        try:
            b = sd.query(_db(gcp, run), gq)[0]["c"]
        except Exception as e:  # noqa: BLE001
            b = f"ERROR {str(e)[:200]}"
        res[name] = (a, b)
    bad = {k: v for k, v in res.items() if not (isinstance(v, tuple) and v[0] == v[1])}
    check(not bad, None, "C-05/C-11/F-10/B-16(GQL)", f"cypher vs gql: {res}", severity="P1")


@pytest.mark.t3
def test_L05_data_hygiene(gcp, e2e):
    p = subprocess.run(["gcloud", "storage", "ls", "--recursive", gcp.gcs_prefix], capture_output=True, text=True)
    outside = [l for l in p.stdout.splitlines() if l.startswith("gs://") and not l.startswith(gcp.gcs_prefix)]
    check(not outside, None, "L-05", f"{len(p.stdout.splitlines())} objects under {gcp.gcs_prefix}; outside={outside[:3]}")


# ============================================================================ T4: verify trustworthiness

def _verify_baseline_failures(v: dict) -> set[str]:
    rep = v.get("report") or {}
    s = set()
    for c in rep.get("counts", []):
        if not c["passed"]:
            s.add(f"count:{c['table']}")
    for smp in rep.get("samples", []):
        for m in smp["mismatches"]:
            s.add(f"sample:{smp['table']}:{m.get('column', m.get('error'))}:{json.dumps(m.get('pk'), sort_keys=True, default=str)}")
    for q in rep.get("queries", []):
        if not q["passed"]:
            s.add(f"query:{q['name']}")
    return s


@pytest.mark.t4
def test_H06_baseline_verify_false_failures(e2e):
    runs, _ = e2e
    r2 = runs["r2"]
    if r2.load.rc != 0 or not r2.verify:
        pytest.skip("R2 not loaded/verified in this session")
    res = {n: sorted(_verify_baseline_failures(r.verify))[:20] for n, r in runs.items() if r.verify}
    r2f = res.get("r2", [])
    crashed = r2.verify.get("traceback") or "report" not in r2.verify
    pk_false = [f for f in r2f if any(t in f for t in ("PkWide", "PkTs", "PkBytes", "PkFloat", "REL_B", "REL_D"))]
    check(not crashed and not pk_false, "H19", "H-06",
          f"R2 baseline verify rc={r2.verify.get('rc')} crashed={bool(crashed)} stderr_tail={r2.verify.get('stderr', '')[-300:]!r}; "
          f"failures={json.dumps(res)[:2200]}", severity="P1",
          title="verify crashes or reports false missing_in_neo4j for TIMESTAMP/BYTES/widened primary keys")
    record(None, "H-06(all)", "Observation", f"baseline verify rc: { {n: r.verify.get('rc') for n, r in runs.items() if r.verify} }; failures: {json.dumps(res)[:3000]}")


def _mutate_and_verify(run: Run, gcp, mutate_sql: str, revert_sql: str, tag: str, **vk) -> tuple[dict, set[str]]:
    db = _db(gcp, run)
    sd.execute_dml(db, mutate_sql)
    try:
        v = run_verify(run, gcp, tag=tag, **vk)
    finally:
        sd.execute_dml(db, revert_sql)
    new = _verify_baseline_failures(v) - _verify_baseline_failures(run.verify)
    return v, new


def _r2(e2e):
    runs, _ = e2e
    r = runs["r2"]
    if r.load.rc != 0 or not r.verify:
        pytest.skip("R2 not loaded")
    return r


@pytest.mark.t4
def test_H01_golden_vs_verify(e2e, r2_diffs):
    runs, _ = e2e
    r2 = runs["r2"]
    rep = r2.verify.get("report") or {}
    vfail = {smp["table"] for smp in rep.get("samples", []) if not smp["passed"]}
    missed = [d for d in r2_diffs if d.get("table") not in vfail]
    check(bool(rep) and not missed, "H01", "H-01(golden-vs-verify)",
          f"golden oracle diffs on rb_r2_01: {[(d.get('table'), d.get('key'), d.get('column')) for d in r2_diffs]}; "
          f"verify sample failures in tables {sorted(vfail)}; golden diffs missed by verify: {missed}", severity="P0",
          title="verify cannot detect lossy conversions (shares coerce_value with the exporter)")


@pytest.mark.t4
def test_H01_string_mutation_detected(e2e, gcp):
    r = _r2(e2e)
    v, new = _mutate_and_verify(r, gcp, "UPDATE PkStr SET ps_note = 'note 5X' WHERE sku = 'S-005'",
                                "UPDATE PkStr SET ps_note = 'note 5' WHERE sku = 'S-005'", "H01")
    check(v["rc"] == 1 and any("PkStr" in x for x in new), "H01", "H-01", f"rc={v['rc']} new failures={sorted(new)[:5]}", severity="P0",
          title="verify misses a 1-character STRING change")


@pytest.mark.t4
def test_H02_H03_count_mutations_detected(e2e, gcp):
    r = _r2(e2e)
    res = {}
    v, new = _mutate_and_verify(r, gcp, "DELETE FROM VInt WHERE case_id = 'zero'",
                                "INSERT INTO VInt (case_id, i_val) VALUES ('zero', 0)", "H02a")
    res["delete_node"] = (v["rc"], sorted(new)[:4])
    v, new = _mutate_and_verify(r, gcp, "DELETE FROM PkStr__REL_A__PkComp WHERE sku = 'S-003'",
                                "INSERT INTO PkStr__REL_A__PkComp (sku, dst_tenant, dst_oid, ra_w) VALUES ('S-003', 'T0', 'O-3', 3)", "H02b")
    res["delete_edge"] = (v["rc"], sorted(new)[:4])
    v, new = _mutate_and_verify(r, gcp, "INSERT INTO PkInt__REL_E__PkStr (n, dst_sku) VALUES (6, 'S-002')",
                                "DELETE FROM PkInt__REL_E__PkStr WHERE n = 6", "H03")
    res["insert_edge"] = (v["rc"], sorted(new)[:4])
    ok = all(x[0] == 1 and any(s.startswith("count:") for s in x[1]) for x in res.values())
    check(ok, None, "H-02/H-03", json.dumps(res), severity="P0", title="verify misses row-count mutations")


@pytest.mark.t4
def test_H04_timestamp_mutation_detected(e2e, gcp):
    r = _r2(e2e)
    res = {}
    for tag, delta in [("1us", "1 MICROSECOND"), ("1ms", "1 MILLISECOND")]:
        v, new = _mutate_and_verify(
            r, gcp, f"UPDATE VDateTime SET dt_val = TIMESTAMP_ADD(dt_val, INTERVAL {delta}) WHERE case_id = 'epoch'",
            "UPDATE VDateTime SET dt_val = TIMESTAMP '1970-01-01T00:00:00Z' WHERE case_id = 'epoch'", f"H04_{tag}")
        res[tag] = (v["rc"], any("VDateTime" in x for x in new))
    check(all(x[1] for x in res.values()), "H02", "H-04", f"detected per delta: {res}", severity="P0",
          title="verify compares TIMESTAMPs only to the millisecond")


@pytest.mark.t4
def test_H05_float_ulp_mutation_detected(e2e, gcp):
    r = _r2(e2e)
    import math as _m

    pi_next = _m.nextafter(3.141592653589793, 4)
    v, new = _mutate_and_verify(r, gcp, f"UPDATE VFloat SET f_val = {pi_next!r} WHERE case_id = 'pi'",
                                "UPDATE VFloat SET f_val = 3.141592653589793 WHERE case_id = 'pi'", "H05a")
    ulp = any("VFloat" in x for x in new)
    m = oracle.load_mapping_yaml(r.bundle.mapping_path)
    cif = m["nodes"]["TConf"]["properties"]["c_if"]
    if (cif.get("override") or cif["resolved"]) == "FLOAT64":
        v2, new2 = _mutate_and_verify(r, gcp, "UPDATE TConf SET c_if = 9007199254740994 WHERE tc_id = 'r3'",
                                      "UPDATE TConf SET c_if = 9007199254740992 WHERE tc_id = 'r3'", "H05b")
        big = any("TConf" in x for x in new2)
    else:
        big = True  # ints > 2^53 now widen to STRING(MAX); sub-case not applicable
    check(ulp and big, "H03", "H-05", f"1-ULP FLOAT64 change detected={ulp}; INT>2^53 in FLOAT64 col changed by 2 detected={big}",
          severity="P1", title="verify float comparison (isclose) hides small changes")


@pytest.mark.t4
def test_H07_sampling_bias(e2e, gcp):
    runs, _ = e2e
    r = runs["r3"]
    if r.load.rc != 0:
        pytest.skip("R3 not loaded")
    db = _db(gcp, r)
    # Corrupt the whole last PK range (rows 50,000..59,999) that the old LIMIT-50k sampler could never reach.
    sd.execute_dml(db, "UPDATE Event SET seq = -1 WHERE eid >= 'E050000'")
    try:
        res = {}
        for seed in (1, 42):
            v = run_verify(r, gcp, sample_rows=10_000, seed=seed, tag=f"H07_{seed}")
            hits = [x for x in _verify_baseline_failures(v) if "Event" in x and "seq" in x]
            res[seed] = (v["rc"], len(hits))
    finally:
        sd.execute_dml(db, "UPDATE Event SET seq = CAST(SUBSTR(eid, 2) AS INT64) WHERE eid >= 'E050000'")
    check(all(x[1] > 0 for x in res.values()), "H20", "H-07",
          f"10,000 rows E050000..E059999 corrupted; verify --sample-rows 10000 mismatches in that range per seed: {res}",
          severity="P2", title="verify sampling never reaches rows beyond the first 50,000 of a table")


@pytest.mark.t4
def test_H08_wrong_graph(e2e, gcp):
    r = _r2(e2e)
    v = run_verify(r, gcp, graph="NoSuchGraph", tag="H08", sample_rows=10)
    qerr = [q for q in (v.get("report") or {}).get("queries", []) if q.get("error")]
    check(v["rc"] == 1 and bool(qerr) and not v["traceback"], None, "H-08", f"rc={v['rc']} query errors={len(qerr)} first={qerr[0]['error'][:150] if qerr else None}")


@pytest.mark.t4
def test_H09_custom_queries_file(e2e, gcp, work_dir):
    r = _r2(e2e)
    res = {}
    files = {
        "malformed_yaml": "queries: [ {name: x, cypher: 'RETURN 1'",
        "bad_cypher_gql": "queries:\n - {name: badcy, cypher: 'MATC (n) RETURN n', gql: 'SELECT 1 AS x'}\n - {name: badgql, cypher: 'RETURN 1 AS x', gql: 'SELEC 1'}\n",
        "nondeterministic": "queries:\n - {name: nd, cypher: 'MATCH (n:PkStr) RETURN n.sku AS s LIMIT 3', gql: 'GRAPH RbR2 MATCH (n:PkStr) RETURN n.sku AS s LIMIT 3'}\n",
    }
    for name, text in files.items():
        f = work_dir / f"{name}.yaml"
        f.write_text(text)
        v = run_verify(r, gcp, queries_file=f, tag=f"H09_{name}", sample_rows=10)
        qs = {q["name"]: (q["passed"], (q.get("error") or "")[:80]) for q in (v.get("report") or {}).get("queries", []) if q["name"] in ("badcy", "badgql", "nd", "x")}
        res[name] = {"rc": v["rc"], "traceback": v["traceback"], "queries": qs}
    ok = not any(x["traceback"] for x in res.values())
    check(ok, "NEW-UX", "H-09", json.dumps(res)[:2500], severity="P2", title="CLI surfaces operational/validation errors as raw tracebacks")


@pytest.mark.t4
def test_H10_report_schema_and_secrets(e2e):
    runs, _ = e2e
    reps = {n: r.verify.get("report") for n, r in runs.items() if r.verify.get("report")}
    keys = {n: sorted(v.keys()) for n, v in reps.items()}
    leak = any(PW in json.dumps(v) for v in reps.values())
    ok = all(k == ["counts", "passed", "queries", "samples"] for k in keys.values()) and not leak
    check(ok, None, "H-10", f"keys={keys} password_in_report={leak}")
