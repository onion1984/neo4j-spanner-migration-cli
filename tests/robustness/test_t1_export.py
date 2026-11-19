"""T1: export-side and CLI integration tests (Neo4j 5.x unless noted)."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness import neo4j_util as nu
from harness import tool
from harness.findings import check, record

from neo4j_spanner_export.config import NodeTableMapping, PropertyMapping, SchemaMapping, load_mapping, save_mapping
from neo4j_spanner_export.serializer import SentinelCollisionError

pytestmark = pytest.mark.t1

PW = "testpassword123"


def _seed(d, *stmts, uniques=()):
    nu.wipe(d)
    for lbl, p in uniques:
        nu.unique(d, lbl, p)
    for s in stmts:
        nu.run(d, s)


def test_A02_connection_errors_ux(neo4j_v5, work_dir):
    cases = {
        "wrong_password": (["--uri", "bolt://localhost:7687"], {"NEO4J_PASSWORD": "wrong"}),
        "unreachable": (["--uri", "bolt://localhost:1"], {"NEO4J_PASSWORD": PW}),
        "tls_mismatch": (["--uri", "neo4j+s://localhost:7687"], {"NEO4J_PASSWORD": PW}),
    }
    res = {}
    for name, (args, env) in cases.items():
        p = tool.cli(["discover", *args, "--output-mapping", str(work_dir / f"{name}.yaml")], env=env, timeout=120)
        out = p.stderr + p.stdout
        res[name] = {"rc": p.returncode, "traceback": tool.has_traceback(out), "partial_file": (work_dir / f"{name}.yaml").exists(),
                     "last": out.strip().splitlines()[-1][:160] if out.strip() else ""}
    ok = all(v["rc"] != 0 and not v["traceback"] and not v["partial_file"] for v in res.values())
    check(ok, "NEW-UX", "A-02", str(res), severity="P2", title="CLI surfaces operational/validation errors as raw tracebacks")


def test_A03_missing_database(neo4j_v5, work_dir):
    p = tool.cli(["discover", "--uri", "bolt://localhost:7687", "--database", "nosuchdb", "--output-mapping",
                  str(work_dir / "m.yaml")], env={"NEO4J_PASSWORD": PW})
    out = p.stderr + p.stdout
    check(p.returncode != 0 and "nosuchdb" in out and not tool.has_traceback(out), "NEW-UX", "A-03",
          f"rc={p.returncode} traceback={tool.has_traceback(out)} last={out.strip().splitlines()[-1][:200]}", severity="P2",
          title="CLI surfaces operational/validation errors as raw tracebacks")


def test_A05_chunk_rows_and_workers(neo4j_v5, work_dir):
    _seed(neo4j_v5, "UNWIND range(1,5) AS i CREATE (:C {cid:i})", uniques=[("C", "cid")])
    m = tool.discover(neo4j_v5, work_dir)
    res = {}
    for name, extra in [("chunk0", ["--chunk-rows", "0"]), ("workers_neg", ["--workers", "-3"]), ("workers64", ["--workers", "64"])]:
        p = tool.cli(["export", "--uri", "bolt://localhost:7687", "--mapping", str(work_dir / "schema_mapping.yaml"),
                      "--output-dir", str(work_dir / name), "--gcs-prefix", "gs://x/y", *extra], env={"NEO4J_PASSWORD": PW})
        out = p.stderr + p.stdout
        res[name] = (p.returncode, tool.has_traceback(out), out.strip().splitlines()[-1][:150])
    ok = (res["chunk0"][0] != 0 and not res["chunk0"][1]
          and (res["workers_neg"][0] == 0 or not res["workers_neg"][1]) and res["workers64"][0] == 0)
    check(ok, "NEW-UX", "A-05", str(res), severity="P2", title="CLI surfaces operational/validation errors as raw tracebacks")


def test_A06_sample_size_type_drift(neo4j_v5, work_dir):
    d = neo4j_v5
    _seed(d, "UNWIND range(1,20) AS i CREATE (:Dr {did: i, v: i})", uniques=[("Dr", "did")])
    m = tool.discover(d, work_dir, sample_size=10)
    nu.run(d, "CREATE (:Dr {did: 999, v: 'not-a-number'})")
    try:
        tool.export(d, work_dir, m)
        ok, ev = False, "export succeeded silently with drifted types"
    except Exception as e:  # noqa: BLE001
        files = sorted(p.name for p in (work_dir / "export_out").rglob("*") if p.is_file()) if (work_dir / "export_out").exists() else []
        msg = f"{type(e).__name__}: {e}"
        ok = not files
        ev = f"export raised {msg[:200]}; partial files left: {files}"
        record(None, "A-06(msg)", "Observation", f"error names table/property: {'Dr' in msg and 'v' in msg}; msg={msg[:200]}")
    check(ok, "H18", "A-06", ev, severity="P1", title="--sample-size type drift crashes export mid-stream and leaves a partial bundle")


def test_A10_invalid_timezone_cli(neo4j_v5, work_dir):
    _seed(neo4j_v5, "CREATE (:T {tid:1})", uniques=[("T", "tid")])
    tool.discover(neo4j_v5, work_dir)
    p = tool.cli(["export", "--uri", "bolt://localhost:7687", "--mapping", str(work_dir / "schema_mapping.yaml"),
                  "--output-dir", str(work_dir / "o"), "--gcs-prefix", "gs://x/y", "--default-timezone", "Mars/Base"],
                 env={"NEO4J_PASSWORD": PW})
    out = p.stderr + p.stdout
    check(p.returncode != 0 and not tool.has_traceback(out), "NEW-UX", "A-10", f"rc={p.returncode} last={out.strip().splitlines()[-1][:200]}",
          severity="P2", title="CLI surfaces operational/validation errors as raw tracebacks")


def test_D10_int64_override_truncates_in_export(neo4j_v5, work_dir):
    d = neo4j_v5
    _seed(d, "CREATE (:Ov {oid:'a', amt: 3.7}), (:Ov {oid:'b', amt: 10.2})", uniques=[("Ov", "oid")])
    m = tool.discover(d, work_dir)
    m.nodes["Ov"].properties["amt"].override = "INT64"
    try:
        b = tool.export(d, work_dir, m)
        lines = tool.all_csv_lines(b.out_dir, "nodes", "Ov")
        ok, ev = not any(l.endswith(",3") for l in lines), f"override amt: INT64 on [3.7, 10.2] -> CSV {lines}"
    except Exception as e:  # noqa: BLE001
        ok, ev = True, f"override amt: INT64 on [3.7, 10.2] rejected at export: {type(e).__name__}: {str(e)[:200]}"
    check(ok, "H04", "D-10(T1)", ev,
          severity="P0", title="INT64 override silently truncates floats / crashes on strings")


def test_E02_sentinel_collision(neo4j_v5, work_dir):
    d = neo4j_v5
    _seed(d, "CREATE (:Sn {snid:'k1', s:'__NULL__'}), (:Sn {snid:'k2', s:'ok'})", uniques=[("Sn", "snid")])
    m = tool.discover(d, work_dir)
    try:
        tool.export(d, work_dir, m)
        first = "no error"
    except SentinelCollisionError as e:
        first = str(e)
    w2 = work_dir / "alt"
    w2.mkdir()
    b = tool.export(d, w2, m, null_string="<<NIL>>")
    ok = all(s in first for s in ["Sn", "s", "k1"]) and b.summary.nodes["Sn"].row_count == 2
    check(ok, None, "E-02", f"first error: {first[:300]}; alt null-string rows={b.summary.nodes['Sn'].row_count}")


def test_E07_oversize_cell_detection(neo4j_v5, work_dir):
    d = neo4j_v5
    _seed(d, "CREATE (:Big {bid:'b1', s: $v})".replace("$v", "'x'"), uniques=[("Big", "bid")])
    nu.run(d, "MATCH (b:Big) SET b.s = $v", v="x" * 2_700_000)  # > STRING(MAX) limit of 2,621,440 chars
    try:
        b = tool.discover_and_export(d, work_dir)
        ok, ev = False, f"2,700,000-char string exported without warning (rows={b.summary.nodes['Big'].row_count}); Spanner STRING(MAX) limit is 2,621,440 chars (10 MiB for BYTES); in T3 such a row was rejected and hung the Dataflow job (NEW-HANG)"
    except Exception as e:  # noqa: BLE001
        ok, ev = True, f"rejected: {e}"
    check(ok, "NEW-SIZE", "E-07", ev, severity="P2", title="Values above Spanner's 10 MiB cell limit are not detected before load")


def test_L01_password_not_logged(neo4j_v5, work_dir):
    _seed(neo4j_v5, "CREATE (:L {lid:1})", uniques=[("L", "lid")])
    p = tool.cli(["--verbose", "discover", "--uri", "bolt://localhost:7687", "--password", PW, "--output-mapping",
                  str(work_dir / "m.yaml")], env={"NEO4J_PASSWORD": ""})
    out = p.stdout + p.stderr + (work_dir / "m.yaml").read_text() + (work_dir / "discovery_report.md").read_text()
    check(PW not in out, None, "L-01", f"rc={p.returncode}; password present in output/artifacts: {PW in out}")
    record(None, "L-01(ps)", "Observation", "--password is visible in the process list / shell history; README recommends NEO4J_PASSWORD env var")


def test_L02_malicious_names(neo4j_any, work_dir):
    ver, d = neo4j_any
    _seed(d, "CREATE (:`a\"; DROP TABLE x; --` {`$(touch /tmp/rb_l02)`: 1, k: 'a'})-[:`r; DELETE`]->(:Safe {k:'b'})")
    m = tool.discover(d, work_dir)
    b = tool.export(d, work_dir, m)
    ddl = (b.out_dir / "schema/01_create_tables.sql").read_text()
    runbook = (b.out_dir / "load_runbook.sh").read_text()
    ok = "DROP TABLE x" not in ddl and "$(touch" not in runbook and not Path("/tmp/rb_l02").exists()
    check(ok, None, f"L-02[{ver}]", f"tables={[n.spanner_table for n in m.nodes.values()]} edges={[e.spanner_table for e in m.edges.values()]}")
    (work_dir / "BUNDLE_FOR_T2").write_text(str(b.out_dir))
