"""Fixture graph seeds (G0-G6, R4) for Neo4j 4.4 / 5.x.

Each seed wipes the database first. Label/property names are chosen so that the *value* fixtures
(G2/G4/G6) do not depend on naming hypotheses (H08/H09): every property name is unique graph-wide.
"""

from __future__ import annotations

import datetime
import random
from typing import Any

from neo4j.spatial import CartesianPoint, WGS84Point
from neo4j.time import Date, DateTime, Duration, Time
import pytz

from harness import neo4j_util as nu

UTC = datetime.timezone.utc
NS_DT = DateTime(2026, 3, 15, 10, 0, 0, 123456789, tzinfo=pytz.utc)
BIG = 2**53 + 1
MIB = 1024 * 1024


def _create_rows(driver: Any, label: str, rows: list[dict[str, Any]], batch: int = 500) -> None:
    for i in range(0, len(rows), batch):
        nu.run(driver, f"UNWIND $rows AS r CREATE (n:`{label}`) SET n = r", rows=rows[i : i + batch])


# ----------------------------------------------------------------------------- G2 values
# (case_id, neo4j_value)  -- the golden expectations live in fixtures/golden_r2.py

STR_CASES: list[tuple[str, Any]] = [
    ("empty", ""),
    ("space", " "),
    ("null_like_suffix", "__NULL__ "),
    ("quoted_null", '"__NULL__"'),
    ("literal_backslash_n", "a\\nb"),
    ("real_lf", "a\nb"),
    ("crlf", "a\r\nb"),
    ("lone_cr", "a\rb"),
    ("trailing_backslash", "end\\"),
    ("double_backslash", "x\\\\y"),
    ("backslash_quote", 'x\\"y'),
    ("quote_edges", '"quoted"'),
    ("delim_edges", "|pipe|,comma,"),
    ("tab", "a\tb"),
    ("nul", "a\x00b"),
    ("line_sep", "a\u2028b\u2029c"),
    ("bom_start", "\ufeffbom"),
    ("rtl", "שלום עולם"),
    ("emoji4", "🚀𝄞😀"),
    ("cjk", "日本語テキスト"),
    ("one_mib", "m" * MIB),
    # ("near_cell_limit", 9.9 MiB) removed after NEW-HANG (D16 workaround): exceeds STRING(MAX) 2,621,440-char limit.
    ("near_char_limit", "z" * 2_600_000),
    ("unicode_escape_text", "\\u0041 not A"),
]
# s_val missing on one row => NULL
INT_CASES = [("min", -(2**63)), ("max", 2**63 - 1), ("zero", 0), ("neg1", -1), ("big53", BIG)]
FLOAT_CASES = [
    ("neg_zero", -0.0), ("subnormal", 5e-324), ("max", 1.7976931348623157e308), ("tenth", 0.1),
    ("tiny", 1e-308), ("nan", float("nan")), ("pinf", float("inf")), ("ninf", float("-inf")), ("pi", 3.141592653589793),
]
BOOL_CASES = [("t", True), ("f", False)]
BYTES_CASES = [("empty", b""), ("nul_ff", b"\x00\xff\x00"), ("five_mib", bytes(random.Random(7).getrandbits(8) for _ in range(5 * MIB)))]
DATE_CASES = [("min", Date(1, 1, 1)), ("max", Date(9999, 12, 31)), ("leap", Date(2024, 2, 29))]
LIST_STR_CASES = [("empty", []), ("one", ["a"]), ("specials", ['p|q', 'c,d', 'q"q', 'b\\s', 'n\nl', '']),
                  ("big", [f"e{i}" for i in range(100_000)])]
LIST_INT_CASES = [("pair", [1, 2]), ("extremes", [BIG, -(2**63), 2**63 - 1]), ("empty", [])]
LIST_FLOAT_CASES = [("mix", [1.0, 2.5]), ("tenth", [0.1, -0.0])]
LIST_BOOL_CASES = [("tf", [True, False])]


def seed_g2_values(driver: Any) -> None:
    for label, prop in [("VStr", "case_id"), ("VInt", "case_id"), ("VFloat", "case_id"), ("VBool", "case_id"),
                        ("VBytes", "case_id"), ("VDate", "case_id"), ("VDateTime", "case_id"),
                        ("VLocalDT", "case_id"), ("VTime", "case_id"), ("VDur", "case_id"), ("VPoint", "case_id"),
                        ("VListStr", "case_id"), ("VListInt", "case_id"), ("VListFloat", "case_id"),
                        ("VListBool", "case_id"), ("VListTemporal", "case_id")]:
        nu.unique(driver, label, prop)
    _create_rows(driver, "VStr", [{"case_id": c, "s_val": v} for c, v in STR_CASES if c != "near_char_limit"])
    nu.run(driver, "CREATE (:VStr {case_id: 'near_char_limit', s_val: $v})", v=dict(STR_CASES)["near_char_limit"])
    nu.run(driver, "CREATE (:VStr {case_id: 'absent'})")
    _create_rows(driver, "VInt", [{"case_id": c, "i_val": v} for c, v in INT_CASES])
    _create_rows(driver, "VFloat", [{"case_id": c, "f_val": v} for c, v in FLOAT_CASES])
    _create_rows(driver, "VBool", [{"case_id": c, "b_val": v} for c, v in BOOL_CASES])
    for c, v in BYTES_CASES:
        nu.run(driver, "CREATE (:VBytes {case_id: $c, by_val: $v})", c=c, v=v)
    _create_rows(driver, "VDate", [{"case_id": c, "d_val": v} for c, v in DATE_CASES])
    # DateTimes built in Cypher so Neo4j owns zone semantics (DST gap/overlap).
    nu.run(driver, """
        CREATE (:VDateTime {case_id:'utc_ns', dt_val: datetime('2026-03-15T10:00:00.123456789Z')})
        CREATE (:VDateTime {case_id:'berlin_gap', dt_val: datetime({year:2026,month:3,day:29,hour:2,minute:30,timezone:'Europe/Berlin'})})
        CREATE (:VDateTime {case_id:'berlin_overlap', dt_val: datetime({year:2026,month:10,day:25,hour:2,minute:30,timezone:'Europe/Berlin'})})
        CREATE (:VDateTime {case_id:'plus14', dt_val: datetime('2026-01-01T00:00:00+14:00')})
        CREATE (:VDateTime {case_id:'minus12', dt_val: datetime('2026-01-01T00:00:00-12:00')})
        CREATE (:VDateTime {case_id:'epoch', dt_val: datetime('1970-01-01T00:00:00Z')})
        CREATE (:VDateTime {case_id:'pre_epoch_us', dt_val: datetime('1969-12-31T23:59:59.999999Z')})
        CREATE (:VDateTime {case_id:'max', dt_val: datetime('9999-12-31T23:59:59.999999999Z')})
        CREATE (:VDateTime {case_id:'min', dt_val: datetime('0001-01-01T00:00:00Z')})
        CREATE (:VLocalDT {case_id:'wall', ldt_val: localdatetime('2026-03-15T14:30:00.5')})
        CREATE (:VTime {case_id:'offset_ns', t_val: time('12:34:56.123456789+01:00')})
        CREATE (:VDur {case_id:'mixed', du_val: duration({months:14, days:3, seconds:5, nanoseconds:7})})
        CREATE (:VDur {case_id:'negative', du_val: duration({days:-2, hours:-3})})
        CREATE (:VListTemporal {case_id:'dates', lt_val: [date('2025-01-01'), date('2025-12-31')]})
    """)
    nu.run(driver, """
        UNWIND $rows AS r CREATE (n:VPoint {case_id: r.c, p_val: r.p})
    """, rows=[
        {"c": "cart2d", "p": CartesianPoint((1.5, -2.25))},
        {"c": "cart3d", "p": CartesianPoint((1.0, 2.0, 3.0))},
        {"c": "wgs2d", "p": WGS84Point((103.8, 1.35))},
        {"c": "wgs3d", "p": WGS84Point((103.8, 1.35, 15.0))},
    ])
    _create_rows(driver, "VListStr", [{"case_id": c, "ls_val": v} for c, v in LIST_STR_CASES])
    _create_rows(driver, "VListInt", [{"case_id": c, "li_val": v} for c, v in LIST_INT_CASES])
    _create_rows(driver, "VListFloat", [{"case_id": c, "lf_val": v} for c, v in LIST_FLOAT_CASES])
    _create_rows(driver, "VListBool", [{"case_id": c, "lb_val": v} for c, v in LIST_BOOL_CASES])


# ----------------------------------------------------------------------------- G4 type conflicts

def seed_g4_types(driver: Any) -> None:
    nu.unique(driver, "TConf", "tc_id")
    nu.run(driver, """
        CREATE (:TConf {tc_id:'r1', c_if: 1,   c_bi: true, c_is: 5,   c_fs: 2.5, c_ds: date('2025-01-01'),
                        c_ld: [1,2], c_lis: [1],   c_lif: [1,2]})
        CREATE (:TConf {tc_id:'r2', c_if: 2.5, c_bi: 1,    c_is: 'x', c_fs: 'y', c_ds: 'z',
                        c_ld: [],    c_lis: ['a'], c_lif: [0.5]})
        CREATE (:TConf {tc_id:'r3', c_if: $big, c_fs: 0.1})
    """, big=BIG)


# ----------------------------------------------------------------------------- G6 primary keys (valid subset)

def seed_g6_pk(driver: Any) -> None:
    nu.unique(driver, "PkStr", "sku")
    nu.unique(driver, "PkInt", "n")
    nu.unique(driver, "PkWide", "wk")
    _create_rows(driver, "PkStr", [{"sku": f"S-{i:03d}", "ps_note": f"note {i}"} for i in range(20)])
    _create_rows(driver, "PkInt", [{"n": i, "pi_note": f"n{i}"} for i in range(1, 31)])  # monotonic
    # Mixed-type unique keys are now rejected by discovery (H06 fix); widen via `override: STRING(MAX)` instead
    # (see r2_input_mapping) so verify's handling of widened PKs (H19) is still exercised.
    nu.run(driver, "CREATE (:PkWide {wk: 1, pw_note:'int'}), (:PkWide {wk: 2, pw_note:'int2'}), (:PkWide {wk: 3, pw_note:'str'})")
    _create_rows(driver, "PkComp", [{"tenant": f"T{i % 3}", "oid": f"O-{i}", "pc_note": i} for i in range(12)])
    nu.run(driver, """
        UNWIND range(0, 9) AS i
        CREATE (:PkTs {ts: datetime('2026-01-01T00:00:00Z') + duration({seconds: i}), pt_note: i})
    """)
    nu.run(driver, "UNWIND range(0, 9) AS i CREATE (:PkFloat {fk: toFloat(i) + 0.25, pf_note: i})")
    for i in range(10):
        nu.run(driver, "CREATE (:PkBytes {bk: $b, pb_note: $i})", b=bytes([0, 255, i]), i=i)
    nu.run(driver, "UNWIND range(0, 14) AS i CREATE (:PkNone {pn_note: i})")
    nu.run(driver, """
        MATCH (s:PkStr), (c:PkComp) WHERE toInteger(substring(s.sku, 2)) = c.pc_note
        CREATE (s)-[:REL_A {ra_w: c.pc_note}]->(c)
    """)
    nu.run(driver, "MATCH (t:PkTs), (w:PkWide) WHERE t.pt_note < 3 CREATE (t)-[:REL_B {rb_w: t.pt_note}]->(w)")
    nu.run(driver, "MATCH (a:PkNone), (b:PkNone) WHERE a.pn_note + 1 = b.pn_note CREATE (a)-[:REL_C]->(b)")
    nu.run(driver, "MATCH (f:PkFloat), (b:PkBytes) WHERE f.pf_note = b.pb_note CREATE (f)-[:REL_D {rd_w: f.pf_note}]->(b)")
    nu.run(driver, "MATCH (i:PkInt), (s:PkStr) WHERE i.n <= 5 AND s.sku = 'S-001' CREATE (i)-[:REL_E]->(s)")


G6_PK_OVERRIDES = {"PkComp": ["tenant", "oid"], "PkTs": ["ts"], "PkFloat": ["fk"], "PkBytes": ["bk"]}


def r2_input_mapping():
    from neo4j_spanner_export.config import NodeTableMapping, PropertyMapping, SchemaMapping

    m = SchemaMapping(pk_overrides=dict(G6_PK_OVERRIDES))
    m.nodes["PkWide"] = NodeTableMapping(
        raw_label="PkWide", spanner_table="PkWide", pk_columns=["wk"], pk_source="uniqueness_constraint",
        properties={"wk": PropertyMapping(raw_name="wk", spanner_column="wk", override="STRING(MAX)")})
    return m


def seed_r2(driver: Any) -> None:
    nu.wipe(driver)
    seed_g2_values(driver)
    seed_g4_types(driver)
    seed_g6_pk(driver)


# ----------------------------------------------------------------------------- G5 topology

def seed_g5_topology(driver: Any, n_person: int = 2000, n_events: int = 60_000, hub_edges: int = 10_000) -> None:
    nu.wipe(driver)
    for lbl, p in [("Person", "pid"), ("Company", "cid"), ("Post", "post_id"), ("Event", "eid"), ("Hub", "hub_id")]:
        nu.unique(driver, lbl, p)
    rng = random.Random(42)
    _create_rows(driver, "Person", [{"pid": f"P{i:05d}", "pname": f"Person {i}", "age": 18 + i % 60} for i in range(n_person)], batch=2000)
    # Multi-label overlap: every 10th person is also an Employee (priority Person), some also Manager.
    nu.run(driver, "MATCH (p:Person) WHERE toInteger(substring(p.pid,1)) % 10 = 0 SET p:Employee")
    nu.run(driver, "MATCH (p:Person) WHERE toInteger(substring(p.pid,1)) % 50 = 0 SET p:Manager")
    _create_rows(driver, "Company", [{"cid": f"C{i:03d}", "cname": f"Co {i}"} for i in range(50)])
    _create_rows(driver, "Post", [{"post_id": f"T{i:04d}", "body": f"post {i} | with, delims \"q\""} for i in range(300)])
    _create_rows(driver, "Event", [{"eid": f"E{i:06d}", "seq": i} for i in range(n_events)], batch=5000)
    nu.run(driver, "CREATE (:Hub {hub_id: 'H1'}), (:Lonely {lonely_note: 'isolated'}), (:Lonely {lonely_note: 'isolated2'})")
    knows = [{"a": f"P{rng.randrange(n_person):05d}", "b": f"P{rng.randrange(n_person):05d}", "w": rng.randrange(100)} for _ in range(6000)]
    knows += [{"a": f"P{i:05d}", "b": f"P{i:05d}", "w": 0} for i in range(0, 50)]  # self-loops
    knows += [{"a": "P00001", "b": "P00002", "w": 1}, {"a": "P00002", "b": "P00003", "w": 1}, {"a": "P00003", "b": "P00001", "w": 1}]
    for i in range(0, len(knows), 2000):
        nu.run(driver, "UNWIND $rows AS r MATCH (a:Person {pid:r.a}), (b:Person {pid:r.b}) CREATE (a)-[:KNOWS {kw: r.w}]->(b)", rows=knows[i:i + 2000])
    # Parallel edges: FOLLOWS repeated 1-3 times between the same pairs (one direction).
    fol = []
    for i in range(500):
        a, b = f"P{rng.randrange(n_person):05d}", f"P{rng.randrange(n_person):05d}"
        for k in range(1 + i % 3):
            fol.append({"a": a, "b": b, "k": k})
    nu.run(driver, "UNWIND $rows AS r MATCH (a:Person {pid:r.a}), (b:Person {pid:r.b}) CREATE (a)-[:FOLLOWS {fk_n: r.k}]->(b)", rows=fol)
    nu.run(driver, "MATCH (p:Person) WITH p, toInteger(substring(p.pid,1)) AS i MATCH (c:Company {cid: 'C' + right('000' + toString(i % 50), 3)}) CREATE (p)-[:WORKS_AT {since: 2000 + i % 25}]->(c)")
    # Same rel type LIKES across three triplets; `weight` only on some (INT64 so CAST(NULL AS INT64) is valid).
    nu.run(driver, "MATCH (p:Person), (t:Post) WHERE toInteger(substring(p.pid,1)) % 7 = toInteger(substring(t.post_id,1)) % 7 AND toInteger(substring(t.post_id,1)) < 30 CREATE (p)-[:LIKES {weight: 1}]->(t)")
    nu.run(driver, "MATCH (p:Person), (c:Company) WHERE toInteger(substring(p.pid,1)) % 97 = toInteger(substring(c.cid,1)) CREATE (p)-[:LIKES]->(c)")
    nu.run(driver, "MATCH (c:Company), (t:Post) WHERE toInteger(substring(c.cid,1)) = toInteger(substring(t.post_id,1)) CREATE (c)-[:LIKES {weight: 5}]->(t)")
    nu.run(driver, f"MATCH (h:Hub {{hub_id:'H1'}}) MATCH (p:Person) WITH h, p LIMIT {hub_edges} CREATE (h)-[:LINKS]->(p)")
    nu.run(driver, f"MATCH (h:Hub {{hub_id:'H1'}}) MATCH (e:Event) WITH h, e ORDER BY e.eid LIMIT {max(0, hub_edges - n_person)} CREATE (h)-[:LINKS_EVENT]->(e)")
    nu.run(driver, "MATCH (e:Event) WHERE e.seq % 1000 = 0 MATCH (p:Person {pid: 'P00007'}) CREATE (p)-[:ATTENDED]->(e)")


G5_LABEL_PRIORITY = ["Person"]


# ----------------------------------------------------------------------------- R4 fragile values

def seed_r4_fragile(driver: Any) -> None:
    nu.wipe(driver)
    nu.unique(driver, "Frag", "fr_id")
    nu.run(driver, "CREATE (:Frag {fr_id:'nan_list', fl_val: $a}), (:Frag {fr_id:'inf_list', fl_val: $b}), (:Frag {fr_id:'ok', fl_val: [1.5]})",
           a=[1.5, float("nan")], b=[float("inf"), 2.0])



def seed_r4_nodes_only(driver: Any) -> None:
    """R4 after the H07 fix: NaN/Inf rows are rejected at export, so load a nodes-only graph (re-tests NEW-NOEDGE)."""
    nu.wipe(driver)
    nu.unique(driver, "Frag", "fr_id")
    nu.run(driver, "CREATE (:Frag {fr_id:'ok', fl_val: [1.5]}), (:Frag {fr_id:'ok2', fl_val: [2.5, -0.0]})")


def seed_r5_reject_probe(driver: Any) -> None:
    """R5: a value that passes the exporter's char-count check but exceeds Spanner's 10 MiB cell size
    (2,600,000 four-byte emoji = 10.4 MB). Probes NEW-HANG (rejected row must not hang / be silent)."""
    nu.wipe(driver)
    nu.unique(driver, "Rj", "rj_id")
    nu.run(driver, "CREATE (:Rj {rj_id:'small', rj_val:'ok'})")
    nu.run(driver, "CREATE (:Rj {rj_id:'emoji_10mb', rj_val:$v})", v="😀" * 2_600_000)
    nu.run(driver, "MATCH (a:Rj {rj_id:'small'}), (b:Rj {rj_id:'emoji_10mb'}) CREATE (a)-[:RJ_REL]->(b)")
