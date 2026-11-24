"""T2: apply tool-generated DDL to empty Spanner databases (no data, no Dataflow)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import re

import pytest

from fixtures import graphs as g
from harness import mapping_builder as mb
from harness import neo4j_util as nu
from harness import spanner_ddl as sd
from harness import tool
from harness.findings import check, record

from neo4j_spanner_export.artifacts import generate_artifacts
from neo4j_spanner_export.config import NodeTableMapping, SchemaMapping
from neo4j_spanner_export.serializer import SerializerConfig

pytestmark = [pytest.mark.t2, pytest.mark.timeout(5400)]


class Rejected(str):
    """generate_artifacts refused the mapping (fail-fast before any Spanner write)."""


def _static(work: Path, name: str, m, graph_name: str = "RbGraph"):
    out = work / name
    try:
        generate_artifacts(m, out, "gs://x/y", SerializerConfig(), graph_name=graph_name)
    except Exception as e:  # noqa: BLE001
        return Rejected(f"{type(e).__name__}: {e}")
    return out


def _static_cases(work: Path) -> dict[str, Path]:
    cases: dict[str, Path] = {}
    # F-03 self-loop with composite PK
    p = mb.node("Acct", ["tenant", "aid"], {"tenant": "STRING(MAX)", "aid": "INT64", "nm": "STRING(MAX)"})
    cases["F03_selfloop_composite"] = _static(work, "F03", mb.mapping([p], [mb.edge(p, "PAYS", p, {"amt": "FLOAT64"}, parallel=True)]))
    # F-04 wide table (1,100 columns)
    wide = mb.node("Wide", ["wid"], {"wid": "STRING(MAX)", **{f"c{i:04d}": "INT64" for i in range(1100)}})
    cases["F04_wide_1100_cols"] = _static(work, "F04", mb.mapping([wide]))
    # F-05 same property name, different types across node labels
    a = mb.node("Person", ["pid"], {"pid": "STRING(MAX)", "code": "INT64"})
    c = mb.node("Company", ["cid"], {"cid": "STRING(MAX)", "code": "STRING(MAX)"})
    cases["F05_prop_type_across_labels"] = _static(work, "F05", mb.mapping([a, c], [mb.edge(a, "WORKS_AT", c)]))
    # F-06 shared rel label, STRING prop missing in one triplet -> CAST(NULL AS STRING(MAX))
    a = mb.node("Person", ["pid"], {"pid": "STRING(MAX)"})
    c = mb.node("Company", ["cid"], {"cid": "STRING(MAX)"})
    cases["F06_cast_null_string_max"] = _static(work, "F06", mb.mapping([a, c], [mb.edge(a, "LIKES", a, {"note": "STRING(MAX)"}), mb.edge(a, "LIKES", c)]))
    # F-07 shared rel label, ARRAY<INT64> vs INT64
    cases["F07_cast_array_to_string"] = _static(work, "F07", mb.mapping([a, c], [mb.edge(a, "TAGS", a, {"val": "ARRAY<INT64>"}), mb.edge(a, "TAGS", c, {"val": "INT64"})]))
    # F-07b shared rel label, INT64 vs STRING (scalar conflict)
    cases["F07b_cast_int_to_string"] = _static(work, "F07b", mb.mapping([a, c], [mb.edge(a, "RATES", a, {"score": "INT64"}), mb.edge(a, "RATES", c, {"score": "STRING(MAX)"})]))
    # F-08 graph names
    n = mb.node("Gn", ["gid"], {"gid": "STRING(MAX)"})
    cases["F08_graph_hyphen"] = _static(work, "F08a", mb.mapping([n]), graph_name="my-graph")
    cases["F08_graph_reserved"] = _static(work, "F08b", mb.mapping([n]), graph_name="Select")
    # C-02 GQL/graph keywords as table names
    kw_nodes = [mb.node(k, ["kid"], {"kid": "STRING(MAX)"}) for k in ["Graph", "Node", "Edge", "Label", "Properties", "Key", "Match", "Return", "Destination", "Source"]]
    cases["C02_gql_keywords"] = _static(work, "C02", mb.mapping(kw_nodes, [mb.edge(kw_nodes[0], "LINKS", kw_nodes[1])]))
    # C-07 FK/index name truncation collision
    a60 = mb.node("A" * 60, ["id"], {"id": "STRING(MAX)"})
    b1, b2 = mb.node("B" * 59 + "1", ["id"], {"id": "STRING(MAX)"}), mb.node("B" * 59 + "2", ["id"], {"id": "STRING(MAX)"})
    cases["C07_fk_name_collision"] = _static(work, "C07", mb.mapping([a60, b1, b2], [mb.edge(a60, "RELX", b1), mb.edge(a60, "RELX", b2)]))
    # C-08 dst_ prefix > 128
    col = "c" * 126
    s, d = mb.node("Src", ["id"], {"id": "STRING(MAX)"}), mb.node("Dst", [col], {col: "STRING(MAX)"})
    cases["C08_dst_prefix_131"] = _static(work, "C08", mb.mapping([s, d], [mb.edge(s, "R", d)]))
    # C-09 backtick / backslash in original names
    bt = mb.node("We`ird\\Label", ["wid"], {"wid": "STRING(MAX)"}, table="WeirdLabel")
    bt.properties["wid"].raw_name = "w`id\\x"
    bt.properties["w`id\\x"] = bt.properties.pop("wid")
    bt.pk_columns = ["w`id\\x"]
    cases["C09_backtick_names"] = _static(work, "C09", mb.mapping([bt]))
    bt2 = mb.node("We`ird", ["wid"], {"wid": "STRING(MAX)"}, table="WeirdLabel2")
    bt2.properties["w`id"] = bt2.properties.pop("wid")
    bt2.properties["w`id"].raw_name = "w`id"
    bt2.pk_columns = ["w`id"]
    cases["C09b_backtick_only"] = _static(work, "C09b", mb.mapping([bt2]))
    # C-11 node label equal to rel type
    k = mb.node("KNOWS", ["kid"], {"kid": "STRING(MAX)"})
    pz = mb.node("Pz", ["pid"], {"pid": "STRING(MAX)"})
    cases["C11_label_eq_reltype"] = _static(work, "C11", mb.mapping([k, pz], [mb.edge(pz, "KNOWS", k)]))
    # A-08 invalid override
    ov = mb.node("Ovr", ["oid"], {"oid": "STRING(MAX)", "age": "INT64"})
    ov.properties["age"].override = "VARCHAR"
    cases["A08_override_varchar"] = _static(work, "A08", mb.mapping([ov]))
    # B-10 illegal PK types
    for t in ["JSON", "ARRAY<STRING(MAX)>"]:
        jn = mb.node("Jpk", ["jk"], {"jk": t, "other": "INT64"})
        cases[f"B10_pk_{t[:5]}"] = _static(work, f"B10_{t[:4]}", mb.mapping([jn]))
    # B-14 nodes-only graph
    cases["B14_nodes_only"] = _static(work, "B14", mb.mapping([mb.node("Solo", ["sid"], {"sid": "STRING(MAX)"})]))
    return cases


def _cases_from_previous_mappings(src: Path, work: Path) -> dict[str, object]:
    """NEW-DISCCRASH workaround: regenerate artifacts with the NEW tool from campaign-1 schema_mapping.yaml files."""
    from neo4j_spanner_export.config import load_mapping

    out: dict[str, object] = {}
    for name, sub in [("R2_values_types_pk", "R2"), ("G5_topology", "G5"), ("G1_baseline", "G1"), ("G3_special_names", "G3")]:
        try:
            m = load_mapping(src / "t2" / sub / "schema_mapping.yaml")
            if sub == "G3":
                m.nodes["VIP Customer"].column_renames["1st"] = "first_x"   # NEW-DIGITNAME rename path
            if sub == "R2":
                m.nodes["TConf"].properties["c_if"].override = "STRING(MAX)"
            out[name] = _static(work, f"{sub}_from_c1", m)
        except Exception as e:  # noqa: BLE001
            out[name] = Rejected(f"{type(e).__name__}: {e}")
    return out


def _neo4j_cases(driver, work: Path) -> dict[str, Path]:
    from scripts.seed_synthetic_graph import seed_graph

    src = os.environ.get("RB_MAPPING_SOURCE")
    if src:
        return _cases_from_previous_mappings(Path(src), work)

    cases: dict[str, Path] = {}
    g.seed_r2(driver)
    cases["R2_values_types_pk"] = tool.discover_and_export(driver, work / "R2", input_mapping=g.r2_input_mapping(), delimiter="|").out_dir
    g.seed_g5_topology(driver, n_person=300, n_events=2000, hub_edges=1000)
    cases["G5_topology"] = tool.discover_and_export(driver, work / "G5", input_mapping=SchemaMapping(label_priority=g.G5_LABEL_PRIORITY), delimiter="\t").out_dir
    seed_graph("bolt://localhost:7688", "neo4j", "testpassword123", "neo4j", include_ambiguous=False)
    inm = SchemaMapping(label_priority=["Product", "Category", "Service", "Account", "Order", "AuditNote"],
                        table_renames={"Order": "Orders"}, pk_overrides={"Order": ["tenant_id", "order_id"]})
    inm.nodes["Product"] = NodeTableMapping(raw_label="Product", spanner_table="Product", pk_columns=["sku"],
                                            pk_source="uniqueness_constraint", column_renames={"order": "order_num"})
    cases["G1_baseline"] = tool.discover_and_export(driver, work / "G1", input_mapping=inm).out_dir
    nu.wipe(driver)
    nu.run(driver, "CREATE (:`VIP Customer` {`first name`: 'a', `e-mail`: 'x@y', `1st`: 1, `_under`: 2, `dot.prop`: 4})-[:`HAS-PART`]->(:`a\"; DROP TABLE x; --` {k:'z'})")
    g3m = SchemaMapping()
    # NEW-DIGITNAME fix: digit-leading aliases are rejected; column_renames now also renames the graph alias.
    g3m.nodes["VIP Customer"] = NodeTableMapping(raw_label="VIP Customer", spanner_table="VIP_Customer", pk_columns=["_neo4j_id"],
                                                 pk_source="neo4j_id_fallback", column_renames={"1st": "first_x"})
    cases["G3_special_names"] = tool.discover_and_export(driver, work / "G3", input_mapping=g3m).out_dir
    return cases


@pytest.fixture(scope="module")
def t2_results(gcp, neo4j_v44_only, work_root):
    work = work_root / "t2"
    work.mkdir(parents=True, exist_ok=True)
    only = [c for c in os.environ.get("RB_T2_CASES", "").split(",") if c]
    cases = _static_cases(work)
    if not only or any(c in only for c in ("R2_values_types_pk", "G5_topology", "G1_baseline", "G3_special_names")):
        cases.update(_neo4j_cases(neo4j_v44_only, work))
    if only:
        cases = {k: v for k, v in cases.items() if k in only}

    def run(item):
        name, out = item
        if isinstance(out, Rejected):
            return name, out
        db_id = ("rb_t2_" + re.sub(r"[^a-z0-9_]", "_", name.lower()))[:30].rstrip("_")
        try:
            res = sd.apply_bundle_ddl(gcp, db_id, out)
        except Exception as e:  # noqa: BLE001
            res = {"setup": sd.DdlResult("setup", 0, [{"index": "-", "statement": "", "error": str(e)}])}
        try:
            gcp.database(db_id).drop()
        except Exception:  # noqa: BLE001
            pass
        return name, res

    with ThreadPoolExecutor(max_workers=int(os.environ.get("RB_T2_WORKERS", "6"))) as pool:
        results = dict(pool.map(run, cases.items()))
    summary = "\n\n".join(f"## {k}\n{_err(v) if isinstance(v, Rejected) else sd.summarize(v)}" for k, v in results.items())
    (work / "t2_summary.txt").write_text(summary)
    return results


def _get(results, name):
    if name not in results:
        pytest.skip(f"case {name} not selected (RB_T2_CASES)")
    return results[name]


def _ok(r) -> bool:
    if isinstance(r, Rejected):
        return False
    return all(x.ok for x in r.values())


def _err(r) -> str:
    if isinstance(r, Rejected):
        return f"REJECTED by tool before Spanner: {r[:600]}"
    return sd.summarize({k: v for k, v in r.items() if not v.ok})[:1500] or "all statements accepted"


def _ok_or_failfast(r, *needles: str) -> bool:
    """Generated DDL accepted by Spanner, OR the tool refused it with an actionable message (PASS negative)."""
    if isinstance(r, Rejected):
        return all(n.lower() in r.lower() for n in needles) if needles else True
    return _ok(r)


@pytest.mark.parametrize("name", ["R2_values_types_pk", "G5_topology", "G1_baseline", "G3_special_names", "F03_selfloop_composite", "B14_nodes_only"])
def test_F01_F02_F03_valid_bundles_apply(t2_results, name):
    _get(t2_results, name)
    hyp = "H25" if name == "B14_nodes_only" else None
    check(_ok(t2_results[name]), hyp, f"F-01[{name}]", _err(t2_results[name]), severity="P0")


def test_F04_limits(t2_results):
    r = t2_results["F04_wide_1100_cols"]
    record(None, "F-04(T2)", "Observation",
           ("generate_artifacts accepts a hand-built 1,100-column mapping (limit enforced in discovery, see F-04(T1)); Spanner: " + _err(r))
           if not isinstance(r, Rejected) else _err(r))


def test_F05_property_type_across_labels(t2_results):
    check(_ok_or_failfast(t2_results["F05_prop_type_across_labels"], "code"), "H08", "F-05", _err(t2_results["F05_prop_type_across_labels"]), severity="P0",
          title="Same property name with different types across node labels breaks CREATE PROPERTY GRAPH")


def test_F06_cast_null_string_max(t2_results):
    check(_ok_or_failfast(t2_results["F06_cast_null_string_max"]), "H09", "F-06", _err(t2_results["F06_cast_null_string_max"]), severity="P0",
          title="Shared edge labels emit CAST(... AS STRING(MAX)) that Spanner rejects")


def test_F07_cast_conflicting_types(t2_results):
    r1, r2 = t2_results["F07_cast_array_to_string"], t2_results["F07b_cast_int_to_string"]
    check(_ok_or_failfast(r1, "val") and _ok_or_failfast(r2, "score"), "H09", "F-07", f"ARRAY vs INT64: {_err(r1)}\nINT64 vs STRING: {_err(r2)}", severity="P0",
          title="Shared edge labels emit CAST(... AS STRING(MAX)) that Spanner rejects")


def test_F08_graph_name_validation(t2_results):
    h, rsv = t2_results["F08_graph_hyphen"], t2_results["F08_graph_reserved"]
    check(isinstance(h, Rejected) and isinstance(rsv, Rejected), "H15", "F-08",
          f"my-graph -> {_err(h)[:400]}; Select -> {_err(rsv)[:400]}", severity="P2",
          title="--graph-name is not validated (DDL injection)")


def test_C02_gql_keywords(t2_results):
    r = _get(t2_results, "C02_gql_keywords")
    check(_ok(r), None, "C-02", _err(r), severity="P1",
          title="Graph/GQL keywords accepted as identifiers but break 05_property_graph.sql")


def test_C07_fk_collision_spanner(t2_results):
    check(_ok_or_failfast(t2_results["C07_fk_name_collision"]), "H11", "C-07", _err(t2_results["C07_fk_name_collision"]), severity="P1",
          title="FK/index names truncated to 128 chars collide")


def test_C08_dst_prefix_spanner(t2_results):
    check(_ok_or_failfast(t2_results["C08_dst_prefix_131"]), "H12", "C-08", _err(t2_results["C08_dst_prefix_131"]), severity="P2",
          title="dst_ prefix pushes destination PK column past 128 chars")


def test_C09_backtick_names(t2_results):
    r1, r2 = t2_results["C09_backtick_names"], t2_results["C09b_backtick_only"]
    check(_ok_or_failfast(r1) and _ok_or_failfast(r2), "H13", "C-09",
          f"backtick+backslash: {_err(r1)[:500]} || backtick only: {_err(r2)[:700]}", severity="P2",
          title="Backticks in original names are escaped Cypher-style (doubled), invalid in GoogleSQL")


def test_C11_label_eq_reltype(t2_results):
    r = _get(t2_results, "C11_label_eq_reltype")
    check(_ok_or_failfast(r, "KNOWS"), "NEW-LABELCLASH", "C-11", _err(r), severity="P2",
          title="A node label and a relationship type with the same name produce conflicting LABEL property sets")


def test_A08_override_varchar_spanner(t2_results):
    r = t2_results["A08_override_varchar"]
    check(_ok_or_failfast(r, "VARCHAR"), "H04", "A-08(T2)", _err(r), severity="P0",
          title="Invalid `override` types are not validated")


def test_B10_illegal_pk_spanner(t2_results):
    rs = {k: _err(v) for k, v in t2_results.items() if k.startswith("B10_")}
    check(all(_ok_or_failfast(t2_results[k], "primary key") for k in rs), "H05", "B-10(T2)", str(rs), severity="P0",
          title="pk_overrides accept ARRAY/JSON columns that Spanner cannot use as keys")
