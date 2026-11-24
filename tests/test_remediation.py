"""Unit tests verifying the remediation of DEF-001 through DEF-038."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from neo4j.time import Date as Neo4jDate
from neo4j.time import DateTime as Neo4jDateTime

from neo4j_spanner_export.artifacts import generate_artifacts
from neo4j_spanner_export.config import ConfigError, SchemaMapping, load_mapping, validate_mapping
from neo4j_spanner_export.discovery import MAX_SPANNER_COLUMNS, _looks_monotonic
from neo4j_spanner_export.exporter import ExportSummary, export_graph
from neo4j_spanner_export.layout import get_edge_columns
from neo4j_spanner_export.naming import (
    NamingError,
    derive_prefixed_identifier,
    validate_gcs_prefix,
    validate_graph_alias,
)
from neo4j_spanner_export.serializer import (
    EMPTY_BYTES_SENTINEL,
    SPANNER_MAX_BYTES_LEN,
    SPANNER_MAX_STRING_CHARS,
    SerializerConfig,
    coerce_value,
)
from neo4j_spanner_export.types import is_legal_pk_type, is_valid_spanner_type, widen_types
from neo4j_spanner_export.verify import _normalize_neo4j_expected, _normalize_spanner_value, _values_equal
from neo4j_spanner_export.writer import WriteResult
from tests.robustness.harness import mapping_builder as mb


def test_def001_002_003_verify_independent_precision() -> None:
    col_ts = SimpleNamespace(final_type="TIMESTAMP", spanner_column="dt", raw_name="dt")
    ndt = Neo4jDateTime(2026, 3, 15, 10, 0, 0, 123456789)
    exp_ts = _normalize_neo4j_expected(ndt, col_ts, "UTC")
    # Spanner DatetimeWithNanoseconds-like object truncated to microseconds
    spanner_trunc = datetime.datetime(2026, 3, 15, 10, 0, 0, 123456, tzinfo=datetime.timezone.utc)
    got_ts = _normalize_spanner_value(spanner_trunc, col_ts)
    assert exp_ts == ("ts", 1773568800, 123456789)
    assert not _values_equal(exp_ts, got_ts, "TIMESTAMP")

    # FLOAT64 exactness: >2^53 int vs rounded float, and 1-ULP diff
    col_f = SimpleNamespace(final_type="FLOAT64", spanner_column="f", raw_name="f")
    big = 2**53 + 1
    assert not _values_equal(
        _normalize_neo4j_expected(big, col_f, "UTC"),
        _normalize_spanner_value(float(big), col_f),
        "FLOAT64",
    )
    assert not _values_equal(1.0, 1.0 + 2.220446049250313e-16, "FLOAT64")


def test_def002_datetime_nanoseconds_coercion() -> None:
    ndt = Neo4jDateTime(2026, 3, 15, 10, 0, 0, 123456789)
    assert coerce_value(ndt, "TIMESTAMP", "UTC") == "2026-03-15T10:00:00.123456789Z"


def test_def003_int_float_large_int_widening_and_guard() -> None:
    assert widen_types({"INT64": 1, "FLOAT64": 1}, has_large_int=True) == ("STRING(MAX)", True)
    with pytest.raises(ValueError, match="2\\^53"):
        coerce_value(2**53 + 1, "FLOAT64")


def test_def004_005_overrides_and_pk_validation(tmp_path: Path) -> None:
    assert not is_valid_spanner_type("VARCHAR")
    assert is_valid_spanner_type("STRING(MAX)")
    assert not is_legal_pk_type("JSON")
    assert not is_legal_pk_type("ARRAY<STRING(MAX)>")
    assert is_legal_pk_type("INT64")

    with pytest.raises(ValueError, match="INT64"):
        coerce_value(3.7, "INT64")
    with pytest.raises(ValueError, match="BOOL"):
        coerce_value("maybe", "BOOL")

    # Invalid override in mapping
    bad_ovr = mb.node("Ovr", ["oid"], {"oid": "STRING(MAX)", "age": "VARCHAR"})
    with pytest.raises(ConfigError, match="VARCHAR"):
        validate_mapping(mb.mapping([bad_ovr]))

    # Illegal PK type (JSON)
    bad_pk = mb.node("Jpk", ["jk"], {"jk": "JSON"})
    with pytest.raises(ConfigError, match="PRIMARY KEY"):
        validate_mapping(mb.mapping([bad_pk]))


def test_def006_009_035_graph_ddl_conflicts(tmp_path: Path) -> None:
    # DEF-006: same property name, different types across node tables
    p = mb.node("Person", ["pid"], {"pid": "STRING(MAX)", "code": "STRING(MAX)"})
    c = mb.node("Company", ["cid"], {"cid": "STRING(MAX)", "code": "INT64"})
    with pytest.raises(NamingError, match="conflicting types"):
        generate_artifacts(mb.mapping([p, c]), tmp_path / "d6", "gs://b/run", SerializerConfig())

    # DEF-009: incompatible ARRAY vs INT64 on shared edge label
    p2 = mb.node("Person", ["pid"], {"pid": "STRING(MAX)"})
    c2 = mb.node("Company", ["cid"], {"cid": "STRING(MAX)"})
    e1 = mb.edge(p2, "TAGS", p2, props={"val": "ARRAY<INT64>"})
    e2 = mb.edge(p2, "TAGS", c2, props={"val": "INT64"})
    with pytest.raises(NamingError, match="conflicting types"):
        generate_artifacts(mb.mapping([p2, c2], [e1, e2]), tmp_path / "d9", "gs://b/run", SerializerConfig())

    # DEF-035: node label and rel_type with same name & different props
    k = mb.node("KNOWS", ["kid"], {"kid": "STRING(MAX)"})
    pz = mb.node("Pz", ["pid"], {"pid": "STRING(MAX)"})
    ek = mb.edge(pz, "KNOWS", k)
    with pytest.raises(NamingError, match="shares LABEL"):
        generate_artifacts(mb.mapping([k, pz], [ek]), tmp_path / "d35", "gs://b/run", SerializerConfig())


def test_def008_017_037_serializer_guards() -> None:
    # DEF-008: NaN/Infinity inside lists rejected
    with pytest.raises(ValueError, match="RFC8259"):
        coerce_value([1.5, float("nan")], "ARRAY<FLOAT64>")
    with pytest.raises(ValueError, match="RFC8259"):
        coerce_value([float("inf")], "JSON")

    # DEF-017: BrokenHydrationObject & out-of-range year rejected
    class BrokenHydrationObject:
        pass

    with pytest.raises(ValueError, match="BrokenHydrationObject|out-of-range"):
        coerce_value(BrokenHydrationObject(), "DATE")
    with pytest.raises(ValueError, match="out of range"):
        coerce_value(Neo4jDate(0, 1, 1), "DATE")

    # DEF-037: Cell size limits
    with pytest.raises(ValueError, match="2621440"):
        coerce_value("a" * (SPANNER_MAX_STRING_CHARS + 1), "STRING(MAX)")
    with pytest.raises(ValueError, match="10 MiB"):
        coerce_value(b"a" * (SPANNER_MAX_BYTES_LEN + 1), "BYTES(MAX)")


def test_def011_018_023_024_naming_and_identifiers(tmp_path: Path) -> None:
    # DEF-011 & DEF-023: prefixed identifier stays <= 128 and avoids truncation collisions
    n1 = derive_prefixed_identifier("fk_", "A" * 60 + "__R__" + "B" * 60 + "1", "_dst")
    n2 = derive_prefixed_identifier("fk_", "A" * 60 + "__R__" + "B" * 60 + "2", "_dst")
    assert len(n1) <= 128 and len(n2) <= 128 and n1 != n2

    dst = derive_prefixed_identifier("dst_", "c" * 126)
    assert len(dst) == 128

    # DEF-018 & DEF-024: digit-leading & backslash graph aliases rejected unless renamed
    with pytest.raises(NamingError):
        validate_graph_alias("1st", "property", "T", "nodes.T.column_renames")
    with pytest.raises(NamingError):
        validate_graph_alias("We`ird\\Label", "LABEL", "T", "table_renames")


def test_def012_019_020_021_022_025_026_033_034_artifacts(tmp_path: Path) -> None:
    # DEF-012: injection blocked
    with pytest.raises(NamingError):
        validate_gcs_prefix("gs://b/$(touch pwned)")

    # DEF-021, DEF-022, DEF-025, DEF-026, DEF-033, DEF-034
    a = mb.node("Item", ["id"], {"id": "STRING(MAX)", "raw": "BYTES(MAX)", "note": "STRING(MAX)"})
    b = mb.node("Empty", ["eid"], {"eid": "STRING(MAX)"})
    m = mb.mapping([a, b])

    summary = ExportSummary(
        nodes={
            "Item": WriteResult("Item", 1, [tmp_path / "nodes" / "Item_part_00000.csv"]),
            "Empty": WriteResult("Empty", 0, []),
        }
    )

    out_tab = tmp_path / "tab"
    generate_artifacts(
        m,
        out_tab,
        "gs://b/run",
        SerializerConfig(delimiter="\t"),
        emit_unescape=True,
        summary=summary,
    )
    rb_tab = (out_tab / "load_runbook.sh").read_text()
    assert "columnDelimiter=\"$'\\t'\"" in rb_tab
    assert "invalidOutputPath=${GCS_PREFIX}/invalid_records/nodes" in rb_tab
    assert "SKIP_DB_CREATE" in rb_tab
    assert "edges_manifest.json" not in rb_tab  # nodes-only (DEF-020)

    # DEF-022: no invalid raw string r'\' in 03_unescape.sql
    unesc = (out_tab / "schema" / "03_unescape.sql").read_text()
    assert "r'\\'" not in unesc
    assert "run_pdml_file" in rb_tab

    # DEF-033: 02d_empty_bytes.sql generated and sentinel encoded
    empty_sql = (out_tab / "schema" / "02d_empty_bytes.sql").read_text()
    assert "SET raw = b''" in empty_sql
    assert coerce_value(b"", "BYTES(MAX)", empty_bytes_sentinel=EMPTY_BYTES_SENTINEL) != ""

    # DEF-026: 0-row table omitted from manifest; explicit shard paths used (DEF-013)
    manifest = json.loads((out_tab / "manifests" / "nodes_manifest.json").read_text())
    assert [t["table_name"] for t in manifest["tables"]] == ["Item"]
    assert manifest["tables"][0]["file_patterns"] == ["gs://b/run/nodes/Item_part_00000.csv"]

    # DEF-025: ~ delimiter switches parameter separator away from ^~^
    out_tilde = tmp_path / "tilde"
    generate_artifacts(m, out_tilde, "gs://b/run", SerializerConfig(delimiter="~"), summary=summary)
    rb_tilde = (out_tilde / "load_runbook.sh").read_text()
    assert "^|^" in rb_tilde
    assert "columnDelimiter=~" in rb_tilde


def test_def029_030_032_036_config_and_discovery(tmp_path: Path) -> None:
    # DEF-029: empty mapping rejected
    with pytest.raises(ConfigError, match="0 node tables"):
        validate_mapping(SchemaMapping())

    # DEF-030 & DEF-032: bad/empty YAML raises ConfigError
    empty_yaml = tmp_path / "empty.yaml"
    empty_yaml.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="empty"):
        load_mapping(empty_yaml)

    unknown_yaml = tmp_path / "unknown.yaml"
    unknown_yaml.write_text("nodes:\n  A:\n    raw_label: A\n    spanner_table: A\n    pk_columns: [id]\n    pk_source: yaml_override\n    colour: red\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Unknown key"):
        load_mapping(unknown_yaml)

    # DEF-036: sequential integers detected regardless of scan order
    assert _looks_monotonic([10, 3, 7, 1, 9, 2, 8, 4, 6, 5])
    assert not _looks_monotonic(["a", "b", "c"])


def test_def001_discover_non_empty_graph_smoke(tmp_path: Path) -> None:
    """Verify discover_schema runs without UnboundLocalError on a non-empty graph with nodes and edges."""
    from neo4j_spanner_export.discovery import discover_schema

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def __iter__(self):
            return iter(self._rows)

        def single(self):
            return self._rows[0] if self._rows else None

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def run(self, query, **kwargs):
            if "dbms.components()" in query:
                return _FakeResult([{"version": "5.23.0", "edition": "community"}])
            if "SHOW CONSTRAINTS" in query:
                return _FakeResult([
                    {"name": "c1", "type": "UNIQUENESS", "entityType": "NODE", "labelsOrTypes": ["Person"], "properties": ["pid"]}
                ])
            if "labels(n) AS lbls, count(*) AS cnt" in query:
                return _FakeResult([{"lbls": ["Person"], "cnt": 1}])
            if "n.`pid` IS NULL" in query:
                return _FakeResult([{"has_null": False}])
            if "MATCH (n:`Person`)" in query:
                return _FakeResult([{"props": {"pid": "p1", "name": "Alice"}, "nid": 1}])
            if "MATCH (a)-[r]->(b)" in query:
                return _FakeResult([{"src": ["Person"], "rel_type": "KNOWS", "dst": ["Person"], "cnt": 1}])
            if "WHERE c > 1" in query:
                return _FakeResult([{"has_parallel": False}])
            if "RETURN properties(r) AS props" in query:
                return _FakeResult([{"props": {"since": 2020}}])
            raise AssertionError(f"Unexpected query: {query}")

    class _FakeDriver:
        def session(self, database=None):
            return _FakeSession()

    out_map = tmp_path / "schema_mapping.yaml"
    mapping = discover_schema(_FakeDriver(), "neo4j", out_map)
    assert "Person" in mapping.nodes
    assert "Person__KNOWS__Person" in mapping.edges


def test_p1_p2_retest_fixes(tmp_path: Path) -> None:
    # DEF-005: partial input mapping loaded with validate=False
    partial = tmp_path / "partial.yaml"
    partial.write_text("label_priority:\n  - A\n", encoding="utf-8")
    loaded = load_mapping(partial, validate=False)
    assert loaded.label_priority == ["A"]

    # DEF-006: table_renames does not rename Graph LABEL
    ord_node = mb.node("Order", ["oid"], {"oid": "STRING(MAX)"})
    m_lbl = mb.mapping([ord_node])
    m_lbl.table_renames["Order"] = "Orders"
    ord_node.spanner_table = "Orders"
    out_lbl = tmp_path / "lbl"
    generate_artifacts(m_lbl, out_lbl, "gs://b/run", SerializerConfig())
    pg_sql = (out_lbl / "schema" / "05_property_graph.sql").read_text()
    assert "LABEL `Order`" in pg_sql
    assert "Orders\n" in pg_sql
    # DEF-007: check_invalid_records in runbook
    rb_sql = (out_lbl / "load_runbook.sh").read_text()
    assert "check_invalid_records" in rb_sql

    # DEF-008: verify decodes base64 bytes from Spanner
    col_b = SimpleNamespace(final_type="BYTES(MAX)", spanner_column="by", raw_name="by")
    assert _normalize_spanner_value(b"YWJj", col_b) == b"abc"

    # DEF-009: year < 1000 zero-padded to 4 digits
    ndt_min = Neo4jDateTime(1, 1, 1, 0, 0, 0, 0)
    assert coerce_value(ndt_min, "TIMESTAMP", "UTC") == "0001-01-01T00:00:00Z"

    # DEF-010: backtick rejected in validate_graph_alias
    with pytest.raises(NamingError):
        validate_graph_alias("We`ird", "LABEL", "T", "table_renames")

    # DEF-012: verify allows int == float for <= 2^53
    assert _values_equal(1, 1.0, "FLOAT64")
    assert not _values_equal(2**53 + 1, float(2**53 + 1), "FLOAT64")


def test_verify_pk_predicate_tostring_override() -> None:
    from neo4j_spanner_export.config import PropertyMapping
    from neo4j_spanner_export.layout import ColumnSpec
    from neo4j_spanner_export.verify import _neo4j_pk_predicate

    pk_col = ColumnSpec(
        raw_name="wk",
        spanner_column="wk",
        staging_column="wk",
        staging_type="STRING(MAX)",
        final_type="STRING(MAX)",
        manifest_type="STRING",
        is_pk=True,
        role="pk",
        source_raw_name="wk",
    )

    # Explicit override to STRING(MAX) on an INT64 Neo4j key (DEF-002 / H19)
    override_prop = PropertyMapping(
        raw_name="wk",
        spanner_column="wk",
        observed={"INT64": 3},
        resolved="INT64",
        is_conflict=False,
        override="STRING(MAX)",
    )
    pred, val = _neo4j_pk_predicate("n", pk_col, override_prop, "pk_0", "1")
    assert pred == "toString(n.`wk`) = $pk_0"
    assert val == "1"

    # Conflicting Neo4j key widened to STRING(MAX)
    conflict_prop = PropertyMapping(
        raw_name="wk",
        spanner_column="wk",
        observed={"INT64": 2, "STRING": 1},
        resolved="STRING(MAX)",
        is_conflict=True,
        override=None,
    )
    pred_c, val_c = _neo4j_pk_predicate("b", pk_col, conflict_prop, "pk_1", "2")
    assert pred_c == "toString(b.`wk`) = $pk_1"
    assert val_c == "2"

    # Native STRING(MAX) key without override or conflict
    str_prop = PropertyMapping(
        raw_name="wk",
        spanner_column="wk",
        observed={"STRING": 3},
        resolved="STRING(MAX)",
        is_conflict=False,
        override=None,
    )
    pred_s, val_s = _neo4j_pk_predicate("n", pk_col, str_prop, "pk_0", "abc")
    assert pred_s == "n.`wk` = $pk_0"
    assert val_s == "abc"


def test_graph_wide_property_conflicts_strict_and_batched(tmp_path: Path) -> None:
    """Bug 1 (Option A) & Bug 2: detect node-node, edge-edge (same & diff rel), node-edge, and case-insensitive conflicts in one pass."""
    from neo4j_spanner_export.artifacts import find_graph_property_conflicts, validate_property_graph_schema
    from neo4j_spanner_export.discovery import render_discovery_report

    a = mb.node("App", ["aid"], {"aid": "STRING(MAX)", "reviewed_at": "STRING(MAX)", "createdAt": "TIMESTAMP"})
    b = mb.node("Svc", ["sid"], {"sid": "STRING(MAX)", "createdat": "STRING(MAX)"})
    e_calls = mb.edge(a, "CALLS", b, props={"confidence": "FLOAT64", "reviewed_at": "TIMESTAMP"})
    e_consumes = mb.edge(a, "CONSUMES", b, props={"confidence": "STRING(MAX)"})
    e_rates_1 = mb.edge(a, "RATES", a, props={"score": "INT64"})
    e_rates_2 = mb.edge(a, "RATES", b, props={"score": "STRING(MAX)"})

    m = mb.mapping([a, b], [e_calls, e_consumes, e_rates_1, e_rates_2])
    conflicts = find_graph_property_conflicts(m)
    assert [c.prop_key for c in conflicts] == ["confidence", "createdat", "reviewed_at", "score"]

    # Batched error reports ALL 4 conflicts at once
    with pytest.raises(NamingError) as exc_info:
        validate_property_graph_schema(m)
    msg = str(exc_info.value)
    assert "Found 4 graph-wide property(s) with conflicting types" in msg
    for prop in ("confidence", "createdAt", "createdat", "reviewed_at", "score"):
        assert prop in msg

    # Discovery report renders all 4 conflicts + property_type_overrides snippet
    report = render_discovery_report(m)
    assert "## Graph-Wide Property Type Conflicts" in report
    assert "property_type_overrides:" in report
    for prop in ("confidence", "reviewed_at", "score"):
        assert prop in report

    # export_graph fails fast BEFORE touching driver or output_dir
    out_dir = tmp_path / "should_not_exist"
    with pytest.raises(NamingError, match="Found 4 graph-wide"):
        export_graph(
            driver=None,
            database="neo4j",
            mapping=m,
            output_dir=out_dir,
            serializer_cfg=SerializerConfig(),
        )
    assert not out_dir.exists()

    # Resolving all 4 via top-level property_type_overrides makes validation & DDL succeed
    m.property_type_overrides = {
        "confidence": "STRING(MAX)",
        "createdAt": "STRING(MAX)",
        "reviewed_at": "STRING(MAX)",
        "score": "STRING(MAX)",
    }
    validate_mapping(m)
    assert find_graph_property_conflicts(m) == []
    assert "## Graph-Wide Property Type Conflicts" not in render_discovery_report(m)
    generate_artifacts(m, tmp_path / "resolved", "gs://b/run", SerializerConfig())
    ddl = (tmp_path / "resolved" / "schema" / "01_create_tables.sql").read_text()
    assert "confidence STRING(MAX)" in ddl
    assert "reviewed_at STRING(MAX)" in ddl


def test_property_type_overrides_precedence_and_validation(tmp_path: Path) -> None:
    """Verify per-table override takes precedence over property_type_overrides, and invalid types fail."""
    from neo4j_spanner_export.config import save_mapping
    from neo4j_spanner_export.layout import get_node_columns

    a = mb.node("App", ["aid"], {"aid": "STRING(MAX)", "ts": "TIMESTAMP", "x": "INT64"})
    a.properties["x"].override = "FLOAT64"
    m = mb.mapping([a])
    m.property_type_overrides = {"ts": "STRING(MAX)", "x": "STRING(MAX)"}

    # Round-trip YAML preserves property_type_overrides without mutating per-table override
    yml = tmp_path / "m.yaml"
    save_mapping(m, yml)
    loaded = load_mapping(yml)
    assert loaded.property_type_overrides == {"ts": "STRING(MAX)", "x": "STRING(MAX)"}
    assert loaded.nodes["App"].properties["ts"].override is None

    cols = {c.raw_name: c.final_type for c in get_node_columns(loaded.nodes["App"], loaded.property_type_overrides)}
    assert cols["ts"] == "STRING(MAX)"
    assert cols["x"] == "FLOAT64"  # per-table override wins

    # Invalid type in property_type_overrides fails validate_mapping
    loaded.property_type_overrides["ts"] = "VARCHAR"
    with pytest.raises(ConfigError, match="property_type_overrides"):
        validate_mapping(loaded)


def test_case_insensitive_label_collision_rejected() -> None:
    """Spanner Graph treats LABEL names case-insensitively across nodes and edges."""
    from neo4j_spanner_export.artifacts import validate_property_graph_schema

    k = mb.node("Knows", ["kid"], {"kid": "STRING(MAX)"})
    p = mb.node("Person", ["pid"], {"pid": "STRING(MAX)"})
    e = mb.edge(p, "KNOWS", k)
    with pytest.raises(NamingError, match="shares LABEL"):
        validate_property_graph_schema(mb.mapping([k, p], [e]))


def test_verify_datetime_widened_to_string_matches_serializer() -> None:
    """Neo4jDateTime widened/overridden to STRING(MAX) must format as UTC 'Z' in verify just like serializer."""
    col_str = SimpleNamespace(final_type="STRING(MAX)", spanner_column="createdAt", raw_name="createdAt")
    ndt = Neo4jDateTime(2026, 1, 28, 17, 46, 6, 78000000, tzinfo=datetime.timezone.utc)
    serialized = coerce_value(ndt, "STRING(MAX)", "UTC")
    expected = _normalize_neo4j_expected(ndt, col_str, "UTC")
    assert serialized == "2026-01-28T17:46:06.078000000Z"
    assert expected == serialized





