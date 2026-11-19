"""Hand-written golden expectations for R2 (G2-values + G4-types + G6-pk).

Rules applied by hand (README 'lossless' + documented conversions, D9):
  * STRING/INT/FLOAT/BOOL/BYTES/DATE: identical to the Neo4j value.
  * DateTime -> TIMESTAMP: same instant, full nanosecond precision.
  * LocalDateTime -> TIMESTAMP: wall clock interpreted in --default-timezone (UTC).
  * TIME/DURATION -> STRING: ISO-8601 text identical to Neo4j's own toString() (fetched from Neo4j at runtime).
  * POINT -> JSON {srid,x,y[,z]}; list of temporals -> JSON array of ISO strings.
  * Lists -> ARRAY<T> with identical elements.
  * Type conflicts widen per README lattice, but values must stay lossless.
"""

from __future__ import annotations

from typing import Any

from fixtures import graphs as g
from harness.oracle import ts, ts_from_iso


def _by_case(cases, col):
    return {(c,): {col: v} for c, v in cases}


def expected_r2(neo4j_tostring: dict[str, dict[str, str]], neo4j_instants: dict[str, tuple],
                c_if_type: str = "FLOAT64") -> dict[str, dict[str, Any]]:
    """neo4j_tostring[label][case_id] = Neo4j toString() of the value; neo4j_instants[case_id] = ('ts', s, ns)."""
    exp: dict[str, dict[str, Any]] = {}
    vstr = _by_case(g.STR_CASES, "s_val")
    vstr[("absent",)] = {"s_val": None}
    exp["VStr"] = {"key": ["case_id"], "rows": vstr}
    exp["VInt"] = {"key": ["case_id"], "rows": _by_case(g.INT_CASES, "i_val")}
    exp["VFloat"] = {"key": ["case_id"], "rows": _by_case(g.FLOAT_CASES, "f_val")}
    exp["VBool"] = {"key": ["case_id"], "rows": _by_case(g.BOOL_CASES, "b_val")}
    exp["VBytes"] = {"key": ["case_id"], "rows": _by_case(g.BYTES_CASES, "by_val")}
    exp["VDate"] = {"key": ["case_id"], "rows": {("min",): {"d_val": "0001-01-01"}, ("max",): {"d_val": "9999-12-31"},
                                                ("leap",): {"d_val": "2024-02-29"}}}
    exp["VDateTime"] = {"key": ["case_id"], "rows": {
        ("utc_ns",): {"dt_val": ts_from_iso("2026-03-15T10:00:00.123456789Z")},
        ("berlin_gap",): {"dt_val": neo4j_instants["berlin_gap"]},
        ("berlin_overlap",): {"dt_val": neo4j_instants["berlin_overlap"]},
        ("plus14",): {"dt_val": ts_from_iso("2025-12-31T10:00:00Z")},
        ("minus12",): {"dt_val": ts_from_iso("2026-01-01T12:00:00Z")},
        ("epoch",): {"dt_val": ts(0, 0)},
        ("pre_epoch_us",): {"dt_val": ts(-1, 999_999_000)},
        ("max",): {"dt_val": ts_from_iso("9999-12-31T23:59:59.999999999Z")},
        ("min",): {"dt_val": ts_from_iso("0001-01-01T00:00:00Z")},
    }}
    exp["VLocalDT"] = {"key": ["case_id"], "rows": {("wall",): {"ldt_val": ts_from_iso("2026-03-15T14:30:00.5Z")}}}
    exp["VTime"] = {"key": ["case_id"], "rows": {(c,): {"t_val": s} for c, s in neo4j_tostring["VTime"].items()}}
    exp["VDur"] = {"key": ["case_id"], "rows": {(c,): {"du_val": s} for c, s in neo4j_tostring["VDur"].items()}}
    exp["VPoint"] = {"key": ["case_id"], "rows": {
        ("cart2d",): {"p_val": {"srid": 7203, "x": 1.5, "y": -2.25}},
        ("cart3d",): {"p_val": {"srid": 9157, "x": 1.0, "y": 2.0, "z": 3.0}},
        ("wgs2d",): {"p_val": {"srid": 4326, "x": 103.8, "y": 1.35}},
        ("wgs3d",): {"p_val": {"srid": 4979, "x": 103.8, "y": 1.35, "z": 15.0}},
    }}
    exp["VListStr"] = {"key": ["case_id"], "rows": _by_case(g.LIST_STR_CASES, "ls_val")}
    exp["VListInt"] = {"key": ["case_id"], "rows": _by_case(g.LIST_INT_CASES, "li_val")}
    exp["VListFloat"] = {"key": ["case_id"], "rows": _by_case(g.LIST_FLOAT_CASES, "lf_val")}
    exp["VListBool"] = {"key": ["case_id"], "rows": _by_case(g.LIST_BOOL_CASES, "lb_val")}
    exp["VListTemporal"] = {"key": ["case_id"], "rows": {("dates",): {"lt_val": ["2025-01-01", "2025-12-31"]}}}
    # c_if holds 1, 2.5 and 2^53+1: lossless requires either exact FLOAT64 (impossible) or the documented STRING fallback.
    cif = {"r1": 1.0, "r2": 2.5, "r3": g.BIG} if c_if_type == "FLOAT64" else {"r1": "1", "r2": "2.5", "r3": str(g.BIG)}
    exp["TConf"] = {"key": ["tc_id"], "rows": {
        ("r1",): {"c_if": cif["r1"], "c_bi": "true", "c_is": "5", "c_fs": "2.5", "c_ds": "2025-01-01",
                  "c_ld": [1, 2], "c_lis": [1], "c_lif": [1.0, 2.0]},
        ("r2",): {"c_if": cif["r2"], "c_bi": "1", "c_is": "x", "c_fs": "y", "c_ds": "z",
                  "c_ld": [], "c_lis": ["a"], "c_lif": [0.5]},
        ("r3",): {"c_if": cif["r3"], "c_bi": None, "c_is": None, "c_fs": "0.1", "c_ds": None,
                  "c_ld": None, "c_lis": None, "c_lif": None},
    }}
    exp["PkStr"] = {"key": ["sku"], "rows": {(f"S-{i:03d}",): {"ps_note": f"note {i}"} for i in range(20)}}
    exp["PkInt"] = {"key": ["n"], "rows": {(i,): {"pi_note": f"n{i}"} for i in range(1, 31)}}
    exp["PkWide"] = {"key": ["wk"], "rows": {("1",): {"pw_note": "int"}, ("2",): {"pw_note": "int2"}, ("3",): {"pw_note": "str"}}}
    exp["PkComp"] = {"key": ["tenant", "oid"], "rows": {(f"T{i % 3}", f"O-{i}"): {"pc_note": i} for i in range(12)}}
    exp["PkTs"] = {"key": ["ts"], "rows": {(ts(1767225600 + i, 0),): {"pt_note": i} for i in range(10)}}
    exp["PkFloat"] = {"key": ["fk"], "rows": {(i + 0.25,): {"pf_note": i} for i in range(10)}}
    exp["PkBytes"] = {"key": ["bk"], "rows": {(bytes([0, 255, i]),): {"pb_note": i} for i in range(10)}}
    exp["PkNone"] = {"key": ["pn_note"], "rows": {(i,): {} for i in range(15)}}
    return exp


EXPECTED_EDGE_COUNTS_R2 = {
    "PkStr__REL_A__PkComp": 12, "PkTs__REL_B__PkWide": 9, "PkNone__REL_C__PkNone": 14,
    "PkFloat__REL_D__PkBytes": 10, "PkInt__REL_E__PkStr": 5,
}
