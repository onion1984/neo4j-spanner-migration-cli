"""T1: discovery-side integration tests against Neo4j 4.4 and 5.x Community."""

from __future__ import annotations

import logging
from pathlib import Path
import re

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
import pytest

from fixtures import graphs as g
from harness import neo4j_util as nu
from harness import tool
from harness.findings import check, record

from neo4j_spanner_export.config import NodeTableMapping, SchemaMapping
from neo4j_spanner_export.discovery import DiscoveryError
from neo4j_spanner_export.naming import NamingError

pytestmark = pytest.mark.t1


def _seed(driver, *stmts, uniques=()):
    nu.wipe(driver)
    for lbl, p in uniques:
        nu.unique(driver, lbl, p)
    for s in stmts:
        nu.run(driver, s)


def _discover_err(driver, work, **kw):
    try:
        m = tool.discover(driver, work, **kw)
        return m, None
    except Exception as e:  # noqa: BLE001
        return None, e


# ----------------------------------------------------------------------------- B: labels / PKs

def test_B01_node_without_labels(neo4j_any, work_dir):
    ver, d = neo4j_any
    _seed(d, "CREATE (:A {x:1}), (), ()")
    m, e = _discover_err(d, work_dir)
    check(isinstance(e, DiscoveryError) and "2 node(s) with no labels" in str(e), None, f"B-01[{ver}]", f"{type(e).__name__}: {e}")


def test_B02_ambiguous_three_way_overlap(neo4j_any, work_dir):
    ver, d = neo4j_any
    _seed(d, "CREATE (:A:B {x:1}), (:B:C {x:2}), (:A:B:C {x:3}), (:A {x:4})")
    m, e = _discover_err(d, work_dir)
    msg = str(e)
    ok = isinstance(e, DiscoveryError) and all(s in msg for s in ["['A', 'B']", "['B', 'C']", "['A', 'B', 'C']"])
    check(ok, None, f"B-02[{ver}]", f"{type(e).__name__}: {msg[:600]}")


def test_B03_two_constrained_labels(neo4j_any, work_dir):
    ver, d = neo4j_any
    _seed(d, "CREATE (:A:B {a:1, b:1})", uniques=[("A", "a"), ("B", "b")])
    m, e = _discover_err(d, work_dir)
    check(isinstance(e, DiscoveryError) and "multiple constrained labels" in str(e), None, f"B-03[{ver}]", str(e)[:400])


def test_B04_label_priority_unknown_and_duplicate(neo4j_any, work_dir):
    ver, d = neo4j_any
    _seed(d, "CREATE (:A:B {x:1}), (:A {x:2})")
    m, e = _discover_err(d, work_dir, label_priority=["Nope", "A", "A"])
    ok = e is None and m.nodes["A"].row_count == 2 and "B" not in m.nodes
    check(ok, None, f"B-04[{ver}]", f"err={e}; nodes={list(m.nodes) if m else None}; priority kept={m.label_priority if m else None}")


# ---- B-05 / B-06 property-based partition invariants

LABELS = ["La", "Lb", "Lc", "Ld"]
_label_sets = st.lists(st.sets(st.sampled_from(LABELS), min_size=1, max_size=3), min_size=1, max_size=12)


@pytest.mark.parametrize("ver", ["v5", "v44"])
def test_B05_B06_partition_invariants(neo4j_drivers, work_root, ver):
    d = neo4j_drivers[ver]
    failures: list[str] = []
    examples = {"n": 0}

    @settings(max_examples=60, deadline=None, suppress_health_check=list(HealthCheck), database=None)
    @given(label_sets=_label_sets, prio=st.permutations(LABELS), edges=st.lists(st.tuples(st.integers(0, 11), st.integers(0, 11)), max_size=25))
    def _prop(label_sets, prio, edges):
        examples["n"] += 1
        nu.wipe(d)
        nodes = [{"i": i, "lbls": sorted(s)} for i, s in enumerate(label_sets)]
        for n in nodes:
            nu.run(d, f"CREATE (x:{':'.join(n['lbls'])} {{nid: $i}})", i=n["i"])
        n_nodes = len(nodes)
        e_cnt = 0
        for a, b in edges:
            if a < n_nodes and b < n_nodes:
                nu.run(d, "MATCH (a {nid:$a}), (b {nid:$b}) CREATE (a)-[:REL {w:1}]->(b)", a=a, b=b)
                e_cnt += 1
        w = work_root / f"B05_{ver}_{examples['n']}"
        w.mkdir(parents=True, exist_ok=True)
        b = tool.discover_and_export(d, w, input_mapping=SchemaMapping(label_priority=list(prio)))
        node_rows = sum(r.row_count for r in b.summary.nodes.values())
        edge_rows = sum(r.row_count for r in b.summary.edges.values())
        # each node exactly once: collect the nid column across node CSVs
        seen: list[str] = []
        for nm in b.mapping.nodes.values():
            for line in tool.all_csv_lines(b.out_dir, "nodes", nm.spanner_table):
                seen.append(line)
        if node_rows != n_nodes or edge_rows != e_cnt or len(seen) != n_nodes:
            failures.append(f"labels={label_sets} prio={prio} nodes {node_rows}/{n_nodes} edges {edge_rows}/{e_cnt}")

    _prop()
    check(not failures, "H29", f"B-05/B-06[{ver}]",
          f"{examples['n']} random graphs; violations={failures[:3]}", severity="P0",
          title="Multi-label partitioning drops/duplicates rows")


def test_B08_uniqueness_with_nulls_falls_back(neo4j_any, work_dir, caplog):
    ver, d = neo4j_any
    _seed(d, "CREATE (:U {k:'a'}), (:U {k:'b'}), (:U {other:1})", uniques=[("U", "k")])
    with caplog.at_level(logging.WARNING):
        m = tool.discover(d, work_dir)
    nm = m.nodes["U"]
    warned = any("contains NULLs" in r.message for r in caplog.records)
    check(nm.is_synthetic_pk and warned, None, f"B-08[{ver}]", f"pk={nm.pk_columns} source={nm.pk_source} warned={warned}")


def test_B09_pk_override_with_duplicates(neo4j_v5, work_dir):
    d = neo4j_v5
    _seed(d, "CREATE (:Ord {code:'X', n:1}), (:Ord {code:'X', n:2}), (:Ord {code:'Y', n:3})")
    try:
        b = tool.discover_and_export(d, work_dir, input_mapping=SchemaMapping(pk_overrides={"Ord": ["code"]}))
        lines = tool.all_csv_lines(b.out_dir, "nodes", "Ord")
        keys = [l.split(",")[0] for l in lines]
        dup = sorted({k for k in keys if keys.count(k) > 1})
        ev = f"pk_overrides Ord:[code] accepted; CSV contains duplicate PK values {dup} -> Dataflow load would hit ALREADY_EXISTS"
        failed_fast = False
    except Exception as e:  # noqa: BLE001
        ev, failed_fast = f"rejected: {e}", True
    check(failed_fast, "H05", "B-09", ev, severity="P0", title="pk_overrides are not checked for uniqueness")


def test_B10_pk_override_illegal_types(neo4j_v5, work_dir):
    d = neo4j_v5
    _seed(d, "CREATE (:J {tags:['a','b'], loc: point({x:1,y:2})}), (:J {tags:['c'], loc: point({x:3,y:4})})")
    res = {}
    for col in ["tags", "loc"]:
        w = work_dir / col
        w.mkdir()
        try:
            b = tool.discover_and_export(d, w, input_mapping=SchemaMapping(pk_overrides={"J": [col]}))
            pk_line = [l for l in (b.out_dir / "schema/01_create_tables.sql").read_text().splitlines() if "PRIMARY KEY" in l or "NOT NULL" in l]
            res[col] = ("accepted", b.mapping.nodes["J"].properties[col].effective_type, pk_line)
        except Exception as e:  # noqa: BLE001
            res[col] = ("rejected", str(e)[:200])
    check(all(v[0] == "rejected" for v in res.values()), "H05", "B-10", f"{res}", severity="P0",
          title="pk_overrides accept ARRAY/JSON columns that Spanner cannot use as keys")


def test_B11_mixed_type_unique_key_collision(neo4j_v5, work_dir):
    d = neo4j_v5
    _seed(d, "CREATE (:K {kid: 1, v:'int'}), (:K {kid: '1', v:'str'})", uniques=[("K", "kid")])
    try:
        b = tool.discover_and_export(d, work_dir)
        keys = [l.split(",")[0] for l in tool.all_csv_lines(b.out_dir, "nodes", "K")]
        ev = f"PK type {b.mapping.nodes['K'].properties['kid'].effective_type}; CSV keys {keys} (two distinct Neo4j keys -> one Spanner key)"
        ok = len(set(keys)) == len(keys)
    except Exception as e:  # noqa: BLE001
        ev, ok = f"rejected: {e}", True
    check(ok, "H06", "B-11", ev, severity="P1", title="Mixed-type unique keys collapse to duplicate STRING PKs")


def test_B12_constraint_on_secondary_label(neo4j_v5, work_dir):
    d = neo4j_v5
    _seed(d, "CREATE (:Person:Employee {emp_id:'e1', name:'a'}), (:Person {name:'b'})", uniques=[("Employee", "emp_id")])
    m = tool.discover(d, work_dir, label_priority=["Person"])
    nm = m.nodes["Person"]
    report = (work_dir / "discovery_report.md").read_text()
    record(None, "B-12", "Observation",
           f"Person table pk={nm.pk_columns} source={nm.pk_source}; Employee constraint ignored silently; report mentions Employee: {'Employee' in report}")


def test_B13_relationship_constraints_not_testable():
    record(None, "B-13", "Not testable", "Relationship/existence/property-type constraints require Neo4j Enterprise (D6)")


def test_B14_empty_database(neo4j_any, work_dir):
    ver, d = neo4j_any
    nu.wipe(d)
    m, e = _discover_err(d, work_dir)
    if e is None:
        b = tool.export(d, work_dir, m)
        sql = (b.out_dir / "schema/05_property_graph.sql").read_text()
        ok = False
        ev = f"empty DB accepted: 0 tables; 05_property_graph.sql = {sql!r}"
    else:
        ok, ev = True, f"rejected: {e}"
    check(ok, "H25", f"B-14[{ver}]", ev, severity="P2", title="Empty database produces invalid `NODE TABLES ()` DDL")


def test_B15_monotonic_heuristic(neo4j_v5, work_dir):
    d = neo4j_v5
    # Keys are strictly sequential, but created in descending order so Neo4j's scan order is descending.
    _seed(d, "UNWIND range(50,1,-1) AS i CREATE (:Seq {sid: i})",
          "UNWIND range(1,50) AS i CREATE (:Rnd {rid: randomUUID()})", uniques=[("Seq", "sid"), ("Rnd", "rid")])
    m = tool.discover(d, work_dir)
    ok = m.nodes["Seq"].monotonic_pk_warning and not m.nodes["Rnd"].monotonic_pk_warning
    check(ok, "NEW-MONO", "B-15", f"sequential INT64 PK 1..50: warn={m.nodes['Seq'].monotonic_pk_warning}; random UUID PK: warn={m.nodes['Rnd'].monotonic_pk_warning} "
          f"(heuristic inspects internal scan order, not key values; store order differs after deletes)", severity="P2",
          title="Monotonic-PK hotspot warning missed when Neo4j scan order differs from key order")


def test_B16_parallel_edge_detection(neo4j_any, work_dir):
    ver, d = neo4j_any
    _seed(d, "CREATE (a:N {k:1}), (b:N {k:2}), (c:M {k:3})",
          "MATCH (a:N {k:1}), (b:N {k:2}) CREATE (a)-[:P]->(b), (a)-[:P]->(b), (b)-[:P]->(a), (a)-[:Q]->(b), (b)-[:Q]->(a)",
          "MATCH (a:N {k:1}) CREATE (a)-[:S]->(a), (a)-[:S]->(a)",
          "MATCH (a:N {k:1}), (c:M) CREATE (a)-[:T]->(c)", uniques=[("N", "k"), ("M", "k")])
    m = tool.discover(d, work_dir)
    got = {k: e.has_parallel_edges for k, e in m.edges.items()}
    exp = {"N__P__N": True, "N__Q__N": False, "N__S__N": True, "N__T__M": False}
    check(got == exp, None, f"B-16[{ver}]", f"parallel flags {got}")


# ----------------------------------------------------------------------------- C: naming

def test_C01_reserved_keywords_fail_fast_and_rename(neo4j_any, work_dir):
    ver, d = neo4j_any
    _seed(d, "CREATE (:Select {`from`: 1, k:'a'})-[:GROUP]->(:Window {k:'b'})")
    m, e = _discover_err(d, work_dir)
    first_ok = isinstance(e, NamingError) and "reserved keyword" in str(e) and "_renames" in str(e)
    inm = SchemaMapping(table_renames={"Select": "SelectT", "Window": "WindowT"})
    inm.nodes["Select"] = NodeTableMapping(raw_label="Select", spanner_table="Select", pk_columns=["_neo4j_id"],
                                           pk_source="neo4j_id_fallback", column_renames={"from": "from_col"})
    m2, e2 = _discover_err(d, work_dir, input_mapping=inm)
    check(first_ok and e2 is None, None, f"C-01[{ver}]", f"first={e}; after renames err={e2}; tables={list(m2.nodes) if m2 else None}")


def test_C03_case_collisions(neo4j_any, work_dir):
    ver, d = neo4j_any
    res = {}
    for name, stmt in [("labels", "CREATE (:Person {a:1}), (:person {a:2})"), ("props", "CREATE (:X {name:'a', Name:'b'})")]:
        _seed(d, stmt)
        _, e = _discover_err(d, work_dir)
        res[name] = (type(e).__name__, "collision" in str(e))
    check(all(v == ("NamingError", True) for v in res.values()), None, f"C-03[{ver}]", str(res))


def test_C04_unicode_names_collide(neo4j_v5, work_dir):
    _seed(neo4j_v5, "CREATE (:人 {x:1}), (:物 {x:2})")
    _, e = _discover_err(neo4j_v5, work_dir)
    check(isinstance(e, NamingError) and "collision" in str(e), None, "C-04", str(e)[:300])


def test_C05_C09_special_names_preserved(neo4j_any, work_dir):
    ver, d = neo4j_any
    _seed(d, "CREATE (:`VIP Customer` {`first name`: 'a', `e-mail`: 'x@y', `1st`: 1, `_under`: 2, `back``tick`: 3, `dot.prop`: 4})")
    m, e = _discover_err(d, work_dir)
    if e:
        check(False, None, f"C-05[{ver}]", f"discovery failed: {e}")
    # Property `1st` starts with a digit: Spanner Graph rejects such aliases (NEW-DIGITNAME). Expect fail-fast + rename path.
    try:
        tool.export(d, work_dir, m)
        first = "export accepted `1st` as a graph property alias"
        failfast = False
    except Exception as exc:  # noqa: BLE001
        first, failfast = f"{type(exc).__name__}: {exc}", "1st" in str(exc) and "rename" in str(exc).lower()
    w2 = work_dir / "renamed"
    w2.mkdir()
    inm = SchemaMapping()
    inm.nodes["VIP Customer"] = NodeTableMapping(raw_label="VIP Customer", spanner_table="VIP_Customer",
                                                 pk_columns=["_neo4j_id"], pk_source="neo4j_id_fallback",
                                                 column_renames={"1st": "first_x", "back`tick": "back_tick_x"})
    try:
        m2 = tool.discover(d, w2, input_mapping=inm)
        b = tool.export(d, w2, m2)
        g_sql = (b.out_dir / "schema/05_property_graph.sql").read_text()
        renamed_ok = "AS `first_x`" in g_sql
        second = f"after column_renames 1st->first_x: export OK, alias present={renamed_ok}"
    except Exception as exc:  # noqa: BLE001
        renamed_ok, second = False, f"after rename still failing: {exc}"
    check(failfast and renamed_ok, "NEW-DIGITNAME", f"C-05[{ver}]", f"first export: {first[:300]}; {second}", severity="P1",
          title="Original property/label names starting with a digit break CREATE PROPERTY GRAPH")


def test_C06_long_names_deterministic(neo4j_any, work_dir):
    ver, d = neo4j_any
    a, r, z = "A" * 140, "R" * 70, "Z" * 140
    _seed(d, f"CREATE (:`{a}` {{`{'p' * 200}`: 1}})-[:`{r}`]->(:`{z}` {{k:1}})", f"CREATE (:`{a}x` {{k:1}})")
    m1 = tool.discover(d, work_dir)
    m2 = tool.discover(d, work_dir)
    names = [n.spanner_table for n in m1.nodes.values()] + [e.spanner_table for e in m1.edges.values()]
    ok = all(len(n) <= 128 for n in names) and len(set(names)) == len(names) and \
        [n.spanner_table for n in m2.nodes.values()] == [n.spanner_table for n in m1.nodes.values()]
    check(ok, None, f"C-06[{ver}]", f"names={[(n[:20] + '…' + n[-10:], len(n)) for n in names]}")


def test_C10_fixed_column_collisions(neo4j_v5, work_dir):
    d = neo4j_v5
    res = {}
    cases = {
        "edge_id_on_parallel": ("CREATE (a:N {k:1}), (b:N {k:2}) CREATE (a)-[:P {edge_id: 1}]->(b), (a)-[:P {edge_id: 2}]->(b)", [("N", "k")]),
        "edge_prop_eq_src_pk": ("CREATE (a:N {k:1}), (b:M {j:2}) CREATE (a)-[:P {k: 9}]->(b)", [("N", "k"), ("M", "j")]),
        "edge_prop_eq_dst_col": ("CREATE (a:N {k:1}), (b:M {j:2}) CREATE (a)-[:P {dst_j: 9}]->(b)", [("N", "k"), ("M", "j")]),
        "secondary_labels_prop": ("CREATE (:A:B {secondary_labels: 'x'}), (:A {secondary_labels:'y'})", []),
    }
    for name, (stmt, uq) in cases.items():
        _seed(d, stmt, uniques=uq)
        _, e = _discover_err(d, work_dir, label_priority=["A"])
        res[name] = type(e).__name__ if e else "ACCEPTED"
    check(all(v in ("DiscoveryError", "NamingError") for v in res.values()), None, "C-10", str(res), severity="P2")


# ----------------------------------------------------------------------------- D (discovery side)

def test_D03_sparse_property_null_counts(neo4j_v5, work_dir):
    _seed(neo4j_v5, "UNWIND range(1,100) AS i CREATE (:S {sid:i})", "MATCH (s:S {sid: 7}) SET s.rare = 'x'", uniques=[("S", "sid")])
    m = tool.discover(neo4j_v5, work_dir)
    p = m.nodes["S"].properties["rare"]
    check(p.null_count == 99 and p.effective_type == "STRING(MAX)", None, "D-03", f"null_count={p.null_count} type={p.effective_type}")


def test_D15_out_of_range_temporal_export(neo4j_v5, work_dir):
    _seed(neo4j_v5, "CREATE (:Y {yid:'y0', d: date('+10000-01-01')}), (:Y {yid:'y1', d: date('2020-01-01')})", uniques=[("Y", "yid")])
    try:
        b = tool.discover_and_export(neo4j_v5, work_dir)
        lines = tool.all_csv_lines(b.out_dir, 'nodes', 'Y')
        ev, ok = f"export succeeded; CSV: {lines}", not any("Hydration" in l for l in lines)
        names_row = False
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        names_row = "y0" in msg or "Y." in msg or "'Y'" in msg
        ok = True
        ev = f"export raised {msg[:300]}"
    check(ok, "H22", "D-15", ev, severity="P1", title="Out-of-range Neo4j dates silently corrupt the CSV")
    record(None, "D-15(msg)", "Observation", f"error identifies table/row: {names_row}")


# ----------------------------------------------------------------------------- I / F-11 / A-09: parity, determinism

def _strip_version(text: str) -> str:
    return re.sub(r"^neo4j_version: .*$", "", text, flags=re.M)


@pytest.mark.parametrize("fixture", ["r2", "g5"])
def test_I01_F11_A09_parity_and_determinism(neo4j_drivers, work_root, fixture):
    outs = {}
    for ver, d in neo4j_drivers.items():
        if fixture == "r2":
            g.seed_r2(d)
            inm = g.r2_input_mapping()
        else:
            g.seed_g5_topology(d, n_person=300, n_events=2000, hub_edges=1000)
            inm = SchemaMapping(label_priority=g.G5_LABEL_PRIORITY)
        runs = []
        for i in range(2):
            w = work_root / f"I01_{fixture}_{ver}_{i}"
            w.mkdir(parents=True, exist_ok=True)
            # run 0: user input mapping; run 1: re-discover feeding run 0's output back in (A-09 round-trip)
            b = tool.discover_and_export(d, w, input_mapping=inm if i == 0 else runs[0].mapping)
            runs.append(b)
        outs[ver] = runs
    def ddl(b):
        return "".join((b.out_dir / "schema" / f).read_text() for f in sorted(p.name for p in (b.out_dir / "schema").glob("*.sql")))
    def csvs(b):
        rows = {}
        for nm in b.mapping.nodes.values():
            if not nm.is_synthetic_pk:
                rows[nm.spanner_table] = sorted(tool.all_csv_lines(b.out_dir, "nodes", nm.spanner_table))
        return rows
    det = {v: (ddl(r[0]) == ddl(r[1]), _strip_version(r[0].mapping_path.read_text()) == _strip_version(r[1].mapping_path.read_text())) for v, r in outs.items()}
    parity_ddl = ddl(outs["v5"][0]) == ddl(outs["v44"][0])
    parity_map = _strip_version(outs["v5"][0].mapping_path.read_text()).replace("neo4j_edition: community", "") == \
        _strip_version(outs["v44"][0].mapping_path.read_text()).replace("neo4j_edition: community", "")
    c5, c4 = csvs(outs["v5"][0]), csvs(outs["v44"][0])
    csv_diff = [t for t in c5 if c5[t] != c4.get(t)]
    ok = all(a and b for a, b in det.values()) and parity_ddl and parity_map and not csv_diff
    check(ok, "NEW-DET" if (parity_ddl and not csv_diff) else None, f"I-01/F-11/A-09[{fixture}]",
          f"determinism(ddl,mapping)={det} parity ddl={parity_ddl} mapping={parity_map} csv tables differing={csv_diff[:5]} "
          f"(mapping diff between 4.4 and 5.x is only the key order of `observed:` type counts)", severity="P2",
          title="schema_mapping.yaml is not byte-identical across Neo4j versions (observed-type key order)")


def test_I04_neo4j_routing_scheme(neo4j_drivers):
    from neo4j import GraphDatabase

    res = {}
    for ver, port in [("v5", 7687), ("v44", 7688)]:
        try:
            with GraphDatabase.driver(f"neo4j://localhost:{port}", auth=("neo4j", "testpassword123")) as drv:
                nu.wipe(drv)
                nu.run(drv, "CREATE (:R {k:1})")
                import tempfile

                with tempfile.TemporaryDirectory() as t:
                    m = tool.discover(drv, Path(t))
                res[ver] = list(m.nodes)
        except Exception as e:  # noqa: BLE001
            res[ver] = f"ERR {e}"
    check(all(v == ["R"] for v in res.values()), None, "I-04", str(res))


def test_F11b_mapping_independent_of_store_order(neo4j_v5, work_root):
    """Same logical graph, two creation orders -> schema_mapping.yaml should be byte-identical."""
    d = neo4j_v5
    texts = []
    for order in ("asc", "desc"):
        rng = "range(1,40)" if order == "asc" else "range(40,1,-1)"
        _seed(d, f"UNWIND {rng} AS i CREATE (:Mx {{mid: i, v: CASE WHEN i % 2 = 0 THEN i ELSE toString(i) END, w: CASE WHEN i % 3 = 0 THEN 1.5 ELSE i END}})",
              uniques=[("Mx", "mid")])
        w = work_root / f"F11b_{order}"
        w.mkdir(parents=True, exist_ok=True)
        tool.discover(d, w)
        texts.append((w / "schema_mapping.yaml").read_text())
    import difflib

    diff = [l for l in difflib.unified_diff(texts[0].splitlines(), texts[1].splitlines(), lineterm="") if l.startswith(("+ ", "- ", "+  ", "-  "))]
    check(texts[0] == texts[1], "NEW-DET", "F-11b", f"mapping differs only by creation order; diff lines: {diff[:8]}", severity="P2",
          title="schema_mapping.yaml is not byte-identical across Neo4j versions (observed-type key order)")


def test_F04_T1_column_limit_detected_by_discovery(neo4j_v5, work_dir):
    props = ", ".join(f"c{i:04d}: {i}" for i in range(1100))
    _seed(neo4j_v5, f"CREATE (:Wide {{wid:'w1', {props}}})", uniques=[("Wide", "wid")])
    m, e = _discover_err(neo4j_v5, work_dir)
    ok = e is not None and "1024" in str(e)
    check(ok, "H23", "F-04(T1)", f"discovery of a 1,101-property label: {type(e).__name__ if e else 'accepted'}: {str(e)[:250]}",
          severity="P2", title="Spanner column-count limit (1024) not detected by discovery")


def test_A09b_partial_input_mapping_accepted(neo4j_any, work_dir):
    """README: --input-mapping preserves label_priority, pk_overrides, table_renames, column_renames.
    Users (and tests/test_integration_neo4j.py) hand-write partial YAML to fix reserved words before
    the first successful discovery. Such partial mappings must be accepted."""
    ver, d = neo4j_any
    _seed(d, "CREATE (:A:B {k:'a', `order`: 1})-[:R]->(:C {k:'c'})")
    variants = {}
    m1 = SchemaMapping(label_priority=["A"])
    m2 = SchemaMapping(label_priority=["A"], pk_overrides={"C": ["k"]})
    m3 = SchemaMapping(label_priority=["A"])
    m3.nodes["A"] = NodeTableMapping(raw_label="A", spanner_table="A", pk_columns=["_neo4j_id"],
                                     pk_source="neo4j_id_fallback", column_renames={"order": "order_num"})
    for name, m in [("label_priority_only", m1), ("pk_overrides_only", m2), ("node_column_renames", m3)]:
        w = work_dir / name
        w.mkdir()
        mm, e = None, None
        try:
            mm = tool.discover(d, w, input_mapping=m, raw_input=True)
        except Exception as exc:  # noqa: BLE001
            e = exc
        # Accepted = the partial mapping was loaded and applied. A later NamingError for the un-renamed reserved word
        # `order` (variants 1/2 deliberately do not rename it) proves the input mapping itself was accepted.
        if e is None or (type(e).__name__ == "NamingError" and "'order'" in str(e) and name != "node_column_renames"):
            variants[name] = "accepted" + ("" if e is None else " (then expected reserved-word NamingError for `order`)")
        else:
            variants[name] = f"{type(e).__name__}: {str(e)[:160]}"
    check(all(v.startswith("accepted") for v in variants.values()) and variants["node_column_renames"] == "accepted", "NEW-INPUTMAP", f"A-09b[{ver}]", str(variants), severity="P1",
          title="Partial --input-mapping files (renames / label_priority / pk_overrides) are rejected by load_mapping validation")
