"""Verification suite: exact counts, sampled row comparison, and Cypher <-> GQL equivalence."""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass, field
import datetime
import json
import logging
import math
from pathlib import Path
import random
from typing import Any
from zoneinfo import ZoneInfo

from google.cloud import spanner
from neo4j.spatial import Point
from neo4j.time import Date as Neo4jDate
from neo4j.time import DateTime as Neo4jDateTime
from neo4j.time import Duration as Neo4jDuration
from neo4j.time import Time as Neo4jTime
import yaml

from .compat import cypher_ident, id_expr, label_where_predicate
from .config import EdgeTripletMapping, NodeTableMapping, SchemaMapping
from .layout import ColumnSpec, get_edge_columns, get_node_columns
from .naming import spanner_backtick
from .serializer import bit_reverse_64
from .types import MAX_SAFE_FLOAT64_INT

logger = logging.getLogger(__name__)


@dataclass
class TableCountCheck:
    table: str
    kind: str
    neo4j_count: int
    spanner_count: int
    passed: bool


@dataclass
class SampleRowCheck:
    table: str
    kind: str
    sampled_rows: int
    mismatches: list[dict[str, Any]] = field(default_factory=list)
    passed: bool = True


@dataclass
class QueryEquivalenceCheck:
    name: str
    cypher: str
    gql: str
    passed: bool
    neo4j_rows: int = 0
    spanner_rows: int = 0
    error: str | None = None
    diff_sample: str | None = None


@dataclass
class VerificationReport:
    passed: bool
    counts: list[TableCountCheck] = field(default_factory=list)
    samples: list[SampleRowCheck] = field(default_factory=list)
    queries: list[QueryEquivalenceCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dt_to_epoch_ns(dt: Any, default_tz: str = "UTC") -> tuple[str, int, int]:
    """Convert a Neo4j DateTime, Spanner DatetimeWithNanoseconds, or Python datetime to ('ts', sec, ns)."""
    if isinstance(dt, Neo4jDateTime):
        ns = int(getattr(dt, "nanosecond", 0))
        native = dt.to_native()
        if native.tzinfo is None:
            native = native.replace(tzinfo=ZoneInfo(default_tz))
        utc = native.astimezone(datetime.timezone.utc)
        epoch_sec = int(utc.replace(microsecond=0).timestamp())
        return ("ts", epoch_sec, ns)
    if isinstance(dt, datetime.datetime):
        ns = int(getattr(dt, "nanosecond", dt.microsecond * 1000))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(default_tz))
        utc = dt.astimezone(datetime.timezone.utc)
        epoch_sec = int(utc.replace(microsecond=0).timestamp())
        return ("ts", epoch_sec, ns)
    raise ValueError(f"Expected datetime/DateTime, got {type(dt).__name__}")


def _neo4j_to_json_val(value: Any, default_tz: str) -> Any:
    """Independent lossless converter from Neo4j values to Python JSON-comparable structures."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, Point):
        d: dict[str, Any] = {"srid": value.srid, "x": value.x, "y": value.y}
        if hasattr(value, "z") and value.z is not None:
            d["z"] = value.z
        return d
    if isinstance(value, Neo4jDateTime):
        ns = int(getattr(value, "nanosecond", 0))
        native = value.to_native()
        if native.tzinfo is None:
            native = native.replace(tzinfo=ZoneInfo(default_tz))
        utc = native.astimezone(datetime.timezone.utc)
        base = f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}T{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}"
        return f"{base}Z" if ns == 0 else f"{base}.{ns:09d}Z"
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo(default_tz))
        return value.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, (Neo4jDate, Neo4jTime, Neo4jDuration)):
        return value.iso_format()
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return f"PT{value.total_seconds()}S"
    if isinstance(value, list):
        return [_neo4j_to_json_val(item, default_tz) for item in value]
    if isinstance(value, dict):
        return {str(k): _neo4j_to_json_val(v, default_tz) for k, v in value.items()}
    return str(value)


def _normalize_spanner_value(val: Any, col: ColumnSpec) -> Any:
    """Normalize a value returned by the Spanner Python client for comparison."""
    if val is None:
        return None
    ft = col.final_type
    if ft == "JSON":
        if isinstance(val, str):
            return json.loads(val)
        if hasattr(val, "serialize"):
            return json.loads(val.serialize())
        return val
    if ft.startswith("ARRAY<"):
        return list(val)
    if ft == "BYTES(MAX)":
        if isinstance(val, (bytes, bytearray, str)):
            return base64.b64decode(val)
        return bytes(val)
    if ft == "TIMESTAMP":
        if isinstance(val, datetime.datetime):
            return _dt_to_epoch_ns(val, "UTC")
        return str(val)
    if ft == "DATE":
        if isinstance(val, datetime.date):
            return val.isoformat()
        return str(val)
    if ft == "FLOAT64":
        return float(val)
    if ft == "INT64":
        return int(val)
    if ft == "BOOL":
        return bool(val)
    return str(val)


def _normalize_neo4j_expected(raw_val: Any, col: ColumnSpec, default_tz: str) -> Any:
    """Independently normalize a raw Neo4j value without sharing exporter coercion."""
    if raw_val is None:
        return None
    ft = col.final_type
    if ft == "JSON" or ft.startswith("ARRAY<"):
        return _neo4j_to_json_val(raw_val, default_tz)
    if ft == "BYTES(MAX)":
        if isinstance(raw_val, (bytes, bytearray)):
            return bytes(raw_val)
        return str(raw_val).encode("utf-8")
    if ft == "TIMESTAMP":
        if isinstance(raw_val, (Neo4jDateTime, datetime.datetime)):
            return _dt_to_epoch_ns(raw_val, default_tz)
        if isinstance(raw_val, Neo4jDate):
            dt = datetime.datetime(raw_val.year, raw_val.month, raw_val.day, tzinfo=ZoneInfo(default_tz))
            return _dt_to_epoch_ns(dt, default_tz)
        return str(raw_val)
    if ft == "DATE":
        if isinstance(raw_val, Neo4jDate):
            return raw_val.iso_format()
        if isinstance(raw_val, datetime.datetime):
            return raw_val.date().isoformat()
        if isinstance(raw_val, datetime.date):
            return raw_val.isoformat()
        return str(raw_val)
    if ft == "FLOAT64":
        if isinstance(raw_val, int) and not isinstance(raw_val, bool):
            return raw_val
        return float(raw_val)
    if ft == "INT64":
        return int(raw_val)
    if ft == "BOOL":
        return bool(raw_val)
    if isinstance(raw_val, Neo4jDateTime):
        return _neo4j_to_json_val(raw_val, default_tz)
    if isinstance(raw_val, (Neo4jTime, Neo4jDuration, Neo4jDate)):
        return raw_val.iso_format()
    if isinstance(raw_val, (datetime.time, datetime.date, datetime.datetime)):
        return raw_val.isoformat()
    if isinstance(raw_val, (bytes, bytearray)):
        return base64.b64encode(bytes(raw_val)).decode("ascii")
    if isinstance(raw_val, (list, dict, Point)):
        return json.dumps(_neo4j_to_json_val(raw_val, default_tz), ensure_ascii=False, separators=(",", ":"))
    if isinstance(raw_val, bool):
        return "true" if raw_val else "false"
    return str(raw_val)


def _values_equal(a: Any, b: Any, final_type: str) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if final_type == "FLOAT64":
        if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
            return True
        if isinstance(a, int) and not isinstance(a, bool) and abs(a) > MAX_SAFE_FLOAT64_INT and isinstance(b, float):
            return False
        if isinstance(b, int) and not isinstance(b, bool) and abs(b) > MAX_SAFE_FLOAT64_INT and isinstance(a, float):
            return False
        return float(a) == float(b)
    if final_type == "ARRAY<FLOAT64>":
        if len(a) != len(b):
            return False
        return all(_values_equal(x, y, "FLOAT64") for x, y in zip(a, b))
    return a == b


def _spanner_pk_to_neo4j_param(val: Any, col: ColumnSpec) -> Any:
    """Convert a Spanner PK value into a Neo4j Python driver-compatible parameter."""
    if val is None:
        return None
    if col.final_type == "TIMESTAMP" and isinstance(val, datetime.datetime):
        ns = int(getattr(val, "nanosecond", val.microsecond * 1000))
        utc = val.replace(tzinfo=datetime.timezone.utc) if val.tzinfo is None else val.astimezone(datetime.timezone.utc)
        return Neo4jDateTime(utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second, ns, tzinfo=datetime.timezone.utc)
    if col.final_type == "BYTES(MAX)":
        if isinstance(val, (bytes, bytearray, str)):
            return base64.b64decode(val)
        return bytes(val)
    return val


def _spanner_query_dicts(database: Any, sql: str, params: dict[str, Any] | None = None, param_types: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with database.snapshot() as snapshot:
        result = snapshot.execute_sql(sql, params=params, param_types=param_types)
        rows = list(result)
        col_names = [f.name for f in result.metadata.row_type.fields]
        return [dict(zip(col_names, r)) for r in rows]


def _check_counts(
    driver: Any,
    neo4j_db: str,
    spanner_db: Any,
    mapping: SchemaMapping,
) -> list[TableCountCheck]:
    checks: list[TableCountCheck] = []

    for nm in mapping.nodes.values():
        excl = label_where_predicate("n", nm.excluded_labels)
        where_sql = f"WHERE {excl} " if excl else ""
        cypher = f"MATCH (n:{cypher_ident(nm.raw_label)}) {where_sql}RETURN count(n) AS cnt"
        with driver.session(database=neo4j_db) as session:
            n_cnt = int(session.run(cypher).single()["cnt"])
        s_rows = _spanner_query_dicts(spanner_db, f"SELECT COUNT(*) AS cnt FROM {nm.spanner_table}")
        s_cnt = int(s_rows[0]["cnt"])
        checks.append(TableCountCheck(nm.spanner_table, "node", n_cnt, s_cnt, n_cnt == s_cnt))

    for em in mapping.edges.values():
        src_node = mapping.nodes[em.src_label]
        dst_node = mapping.nodes[em.dst_label]
        src_excl = label_where_predicate("a", src_node.excluded_labels)
        dst_excl = label_where_predicate("b", dst_node.excluded_labels)
        where_parts = [p for p in (src_excl, dst_excl) if p]
        where_sql = f"WHERE {' AND '.join(where_parts)} " if where_parts else ""
        cypher = (
            f"MATCH (a:{cypher_ident(em.src_label)})-[r:{cypher_ident(em.rel_type)}]->(b:{cypher_ident(em.dst_label)}) "
            f"{where_sql}RETURN count(r) AS cnt"
        )
        with driver.session(database=neo4j_db) as session:
            n_cnt = int(session.run(cypher).single()["cnt"])
        s_rows = _spanner_query_dicts(spanner_db, f"SELECT COUNT(*) AS cnt FROM {em.spanner_table}")
        s_cnt = int(s_rows[0]["cnt"])
        checks.append(TableCountCheck(em.spanner_table, "edge", n_cnt, s_cnt, n_cnt == s_cnt))

    return checks


def _neo4j_pk_predicate(
    alias: str,
    pkc: ColumnSpec,
    pk_prop: Any,
    param_name: str,
    raw_val: Any,
) -> tuple[str, Any]:
    """Build a Cypher PK predicate, using toString() when non-STRING Neo4j keys are widened/overridden to STRING(MAX)."""
    p_val = _spanner_pk_to_neo4j_param(raw_val, pkc)
    non_null_observed = (
        {t for t in pk_prop.observed if t != "NULL"}
        if pk_prop is not None
        else set()
    )
    needs_tostring = (
        pk_prop is not None
        and pkc.final_type == "STRING(MAX)"
        and (
            pk_prop.is_conflict
            or pk_prop.override == "STRING(MAX)"
            or (bool(non_null_observed) and non_null_observed != {"STRING"})
        )
    )
    if needs_tostring:
        return f"toString({alias}.{cypher_ident(pkc.source_raw_name)}) = ${param_name}", str(p_val)
    return f"{alias}.{cypher_ident(pkc.source_raw_name)} = ${param_name}", p_val


def _sample_node_table(
    driver: Any,
    neo4j_db: str,
    spanner_db: Any,
    nm: NodeTableMapping,
    sample_rows: int,
    rng: random.Random,
    default_tz: str,
    property_type_overrides: dict[str, str] | None = None,
) -> SampleRowCheck:
    cols = get_node_columns(nm, property_type_overrides)
    pk_cols = [c for c in cols if c.is_pk]
    pk_names = [c.spanner_column for c in pk_cols]
    all_names = [c.spanner_column for c in cols]

    s_all = _spanner_query_dicts(
        spanner_db,
        f"SELECT {', '.join(all_names)} FROM {nm.spanner_table} TABLESAMPLE RESERVOIR ({sample_rows} ROWS)",
    )
    if not s_all:
        return SampleRowCheck(nm.spanner_table, "node", 0, [], True)

    chosen = s_all
    mismatches: list[dict[str, Any]] = []

    excl = label_where_predicate("n", nm.excluded_labels)
    excl_sql = f" AND {excl}" if excl else ""

    with driver.session(database=neo4j_db) as session:
        for s_row in chosen:
            if nm.is_synthetic_pk:
                rev_id = int(s_row[pk_names[0]])
                orig_id = bit_reverse_64(rev_id)
                rec = session.run(
                    f"MATCH (n:{cypher_ident(nm.raw_label)}) WHERE {id_expr('n')} = $nid{excl_sql} "
                    f"RETURN properties(n) AS props, labels(n) AS lbls, {id_expr('n')} AS nid",
                    nid=orig_id,
                ).single()
            else:
                predicates = []
                params: dict[str, Any] = {}
                for i, pkc in enumerate(pk_cols):
                    pk_prop = nm.properties.get(pkc.source_raw_name)
                    pred, p_val = _neo4j_pk_predicate("n", pkc, pk_prop, f"pk_{i}", s_row[pkc.spanner_column])
                    predicates.append(pred)
                    params[f"pk_{i}"] = p_val
                rec = session.run(
                    f"MATCH (n:{cypher_ident(nm.raw_label)}) WHERE {' AND '.join(predicates)}{excl_sql} "
                    f"RETURN properties(n) AS props, labels(n) AS lbls, {id_expr('n')} AS nid",
                    **params,
                ).single()

            if rec is None:
                mismatches.append({"pk": {k: str(s_row[k]) for k in pk_names}, "error": "missing_in_neo4j"})
                continue

            props = rec["props"] or {}
            lbls = list(rec["lbls"] or [])
            nid = int(rec["nid"])

            for col in cols:
                if col.role == "pk" and nm.is_synthetic_pk:
                    raw_n = bit_reverse_64(nid)
                elif col.role == "secondary_labels":
                    raw_n = sorted(l for l in lbls if l != nm.raw_label)
                else:
                    raw_n = props.get(col.raw_name)

                exp = _normalize_neo4j_expected(raw_n, col, default_tz)
                got = _normalize_spanner_value(s_row[col.spanner_column], col)
                if not _values_equal(exp, got, col.final_type):
                    mismatches.append(
                        {
                            "pk": {k: str(s_row[k]) for k in pk_names},
                            "column": col.spanner_column,
                            "expected": repr(exp),
                            "actual": repr(got),
                        }
                    )
                    if len(mismatches) >= 20:
                        return SampleRowCheck(nm.spanner_table, "node", len(chosen), mismatches, False)

    return SampleRowCheck(nm.spanner_table, "node", len(chosen), mismatches, len(mismatches) == 0)


def _sample_edge_table(
    driver: Any,
    neo4j_db: str,
    spanner_db: Any,
    em: EdgeTripletMapping,
    src_node: NodeTableMapping,
    dst_node: NodeTableMapping,
    sample_rows: int,
    rng: random.Random,
    default_tz: str,
    property_type_overrides: dict[str, str] | None = None,
) -> SampleRowCheck:
    cols = get_edge_columns(em, src_node, dst_node, property_type_overrides)
    pk_cols = [c for c in cols if c.is_pk]
    pk_names = [c.spanner_column for c in pk_cols]
    all_names = [c.spanner_column for c in cols]

    s_all = _spanner_query_dicts(
        spanner_db,
        f"SELECT {', '.join(all_names)} FROM {em.spanner_table} TABLESAMPLE RESERVOIR ({sample_rows} ROWS)",
    )
    if not s_all:
        return SampleRowCheck(em.spanner_table, "edge", 0, [], True)

    chosen = s_all
    mismatches: list[dict[str, Any]] = []

    src_excl = label_where_predicate("a", src_node.excluded_labels)
    dst_excl = label_where_predicate("b", dst_node.excluded_labels)
    excl_parts = [p for p in (src_excl, dst_excl) if p]

    with driver.session(database=neo4j_db) as session:
        for s_row in chosen:
            predicates = list(excl_parts)
            params: dict[str, Any] = {}
            for i, pkc in enumerate(pk_cols):
                val = s_row[pkc.spanner_column]
                if pkc.role == "src_pk":
                    if src_node.is_synthetic_pk:
                        predicates.append(f"{id_expr('a')} = $pk_{i}")
                        params[f"pk_{i}"] = bit_reverse_64(int(val))
                    else:
                        pk_prop = src_node.properties.get(pkc.source_raw_name)
                        pred, p_val = _neo4j_pk_predicate("a", pkc, pk_prop, f"pk_{i}", val)
                        predicates.append(pred)
                        params[f"pk_{i}"] = p_val
                elif pkc.role == "dst_pk":
                    if dst_node.is_synthetic_pk:
                        predicates.append(f"{id_expr('b')} = $pk_{i}")
                        params[f"pk_{i}"] = bit_reverse_64(int(val))
                    else:
                        pk_prop = dst_node.properties.get(pkc.source_raw_name)
                        pred, p_val = _neo4j_pk_predicate("b", pkc, pk_prop, f"pk_{i}", val)
                        predicates.append(pred)
                        params[f"pk_{i}"] = p_val
                elif pkc.role == "edge_id":
                    predicates.append(f"{id_expr('r')} = $pk_{i}")
                    params[f"pk_{i}"] = int(val)

            cypher = (
                f"MATCH (a:{cypher_ident(em.src_label)})-[r:{cypher_ident(em.rel_type)}]->(b:{cypher_ident(em.dst_label)}) "
                f"WHERE {' AND '.join(predicates)} RETURN properties(r) AS r_props"
            )
            rec = session.run(cypher, **params).single()
            if rec is None:
                mismatches.append({"pk": {k: str(s_row[k]) for k in pk_names}, "error": "missing_in_neo4j"})
                continue

            r_props = rec["r_props"] or {}
            for col in cols:
                if col.is_pk:
                    continue
                raw_n = r_props.get(col.raw_name)
                exp = _normalize_neo4j_expected(raw_n, col, default_tz)
                got = _normalize_spanner_value(s_row[col.spanner_column], col)
                if not _values_equal(exp, got, col.final_type):
                    mismatches.append(
                        {
                            "pk": {k: str(s_row[k]) for k in pk_names},
                            "column": col.spanner_column,
                            "expected": repr(exp),
                            "actual": repr(got),
                        }
                    )
                    if len(mismatches) >= 20:
                        return SampleRowCheck(em.spanner_table, "edge", len(chosen), mismatches, False)

    return SampleRowCheck(em.spanner_table, "edge", len(chosen), mismatches, len(mismatches) == 0)


def _default_equivalence_queries(mapping: SchemaMapping, graph_name: str) -> list[dict[str, str]]:
    queries: list[dict[str, str]] = []

    for nm in mapping.nodes.values():
        excl = label_where_predicate("n", nm.excluded_labels)
        where_sql = f"WHERE {excl} " if excl else ""
        queries.append(
            {
                "name": f"count_node_{nm.spanner_table}",
                "cypher": f"MATCH (n:{cypher_ident(nm.raw_label)}) {where_sql}RETURN count(n) AS cnt",
                "gql": f"GRAPH {graph_name} MATCH (n:{spanner_backtick(nm.raw_label)}) RETURN COUNT(*) AS cnt",
            }
        )

    seen_rel_types: set[str] = set()
    for em in mapping.edges.values():
        if em.rel_type in seen_rel_types:
            continue
        seen_rel_types.add(em.rel_type)
        queries.append(
            {
                "name": f"count_edge_{em.rel_type}",
                "cypher": f"MATCH ()-[r:{cypher_ident(em.rel_type)}]->() RETURN count(r) AS cnt",
                "gql": f"GRAPH {graph_name} MATCH ()-[r:{spanner_backtick(em.rel_type)}]->() RETURN COUNT(*) AS cnt",
            }
        )

    for em in list(mapping.edges.values())[:5]:
        src_node = mapping.nodes[em.src_label]
        dst_node = mapping.nodes[em.dst_label]
        src_excl = label_where_predicate("a", src_node.excluded_labels)
        dst_excl = label_where_predicate("b", dst_node.excluded_labels)
        where_parts = [p for p in (src_excl, dst_excl) if p]
        where_sql = f"WHERE {' AND '.join(where_parts)} " if where_parts else ""
        queries.append(
            {
                "name": f"hop1_{em.spanner_table}",
                "cypher": (
                    f"MATCH (a:{cypher_ident(em.src_label)})-[r:{cypher_ident(em.rel_type)}]->(b:{cypher_ident(em.dst_label)}) "
                    f"{where_sql}RETURN count(r) AS cnt"
                ),
                "gql": (
                    f"GRAPH {graph_name} "
                    f"MATCH (a:{spanner_backtick(em.src_label)})-[r:{spanner_backtick(em.rel_type)}]->(b:{spanner_backtick(em.dst_label)}) "
                    f"RETURN COUNT(*) AS cnt"
                ),
            }
        )

    return queries


def _norm_result_rows(rows: list[dict[str, Any]]) -> list[tuple[str, ...]]:
    out = []
    for r in rows:
        out.append(tuple(json.dumps(r[k], sort_keys=True, default=str) for k in sorted(r)))
    return sorted(out)


def _run_equivalence_suite(
    driver: Any,
    neo4j_db: str,
    spanner_db: Any,
    queries: list[dict[str, str]],
) -> list[QueryEquivalenceCheck]:
    results: list[QueryEquivalenceCheck] = []
    for q in queries:
        name = q["name"]
        cypher = q["cypher"]
        gql = q["gql"]
        try:
            with driver.session(database=neo4j_db) as session:
                n_rows = [dict(r) for r in session.run(cypher)]
            s_rows = _spanner_query_dicts(spanner_db, gql)
            n_norm = _norm_result_rows(n_rows)
            s_norm = _norm_result_rows(s_rows)
            passed = n_norm == s_norm
            diff = None if passed else f"neo4j={n_norm[:3]} spanner={s_norm[:3]}"
            results.append(
                QueryEquivalenceCheck(
                    name=name,
                    cypher=cypher,
                    gql=gql,
                    passed=passed,
                    neo4j_rows=len(n_rows),
                    spanner_rows=len(s_rows),
                    diff_sample=diff,
                )
            )
        except Exception as exc:
            results.append(
                QueryEquivalenceCheck(
                    name=name,
                    cypher=cypher,
                    gql=gql,
                    passed=False,
                    error=str(exc),
                )
            )
    return results


def verify_migration(
    driver: Any,
    neo4j_db: str,
    mapping: SchemaMapping,
    project: str,
    instance: str,
    database: str,
    graph_name: str = "MigratedGraph",
    sample_rows: int = 10_000,
    seed: int = 42,
    default_tz: str = "UTC",
    queries_file: Path | None = None,
    output_report_path: Path | None = None,
) -> VerificationReport:
    """Run full verification (counts, sampled rows, Cypher <-> GQL equivalence)."""
    client = spanner.Client(project=project)
    spanner_db = client.instance(instance).database(database)
    rng = random.Random(seed)

    counts = _check_counts(driver, neo4j_db, spanner_db, mapping)

    samples: list[SampleRowCheck] = []
    for nm in mapping.nodes.values():
        samples.append(
            _sample_node_table(
                driver,
                neo4j_db,
                spanner_db,
                nm,
                sample_rows,
                rng,
                default_tz,
                property_type_overrides=mapping.property_type_overrides,
            )
        )
    for em in mapping.edges.values():
        samples.append(
            _sample_edge_table(
                driver,
                neo4j_db,
                spanner_db,
                em,
                mapping.nodes[em.src_label],
                mapping.nodes[em.dst_label],
                sample_rows,
                rng,
                default_tz,
                property_type_overrides=mapping.property_type_overrides,
            )
        )

    queries = _default_equivalence_queries(mapping, graph_name)
    if queries_file and queries_file.exists():
        custom = yaml.safe_load(queries_file.read_text(encoding="utf-8")) or []
        if isinstance(custom, dict):
            custom = custom.get("queries", [])
        queries.extend(custom)

    query_checks = _run_equivalence_suite(driver, neo4j_db, spanner_db, queries)

    all_passed = (
        all(c.passed for c in counts)
        and all(s.passed for s in samples)
        and all(q.passed for q in query_checks)
    )
    report = VerificationReport(
        passed=all_passed,
        counts=counts,
        samples=samples,
        queries=query_checks,
    )

    if output_report_path is not None:
        output_report_path.parent.mkdir(parents=True, exist_ok=True)
        output_report_path.write_text(
            json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8"
        )

    return report
