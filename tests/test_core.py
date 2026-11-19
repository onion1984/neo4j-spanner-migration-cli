"""Unit tests for naming, type widening, serializer, writer, compat, and artifacts."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from neo4j.spatial import CartesianPoint
from neo4j.time import Date as Neo4jDate
from neo4j.time import DateTime as Neo4jDateTime
from neo4j.time import Duration as Neo4jDuration

from neo4j_spanner_export.artifacts import generate_artifacts
from neo4j_spanner_export.compat import parse_constraint_records, parse_version_tuple
from neo4j_spanner_export.config import (
    EdgeTripletMapping,
    NodeTableMapping,
    PropertyMapping,
    SchemaMapping,
)
from neo4j_spanner_export.naming import (
    NamingError,
    resolve_identifiers,
    sanitize_identifier,
)
from neo4j_spanner_export.serializer import (
    SentinelCollisionError,
    SerializerConfig,
    SerializerConfigError,
    bit_reverse_64,
    coerce_value,
    format_field,
)
from neo4j_spanner_export.types import classify_value, widen_types
from neo4j_spanner_export.writer import ShardedDelimitedWriter


def test_version_and_constraint_parsing() -> None:
    assert parse_version_tuple("5.23.0") == (5, 23, 0)
    assert parse_version_tuple("4.4.35-aura") == (4, 4, 35)

    rows = [
        {"name": "c1", "type": "UNIQUENESS", "entityType": "NODE", "labelsOrTypes": ["Product"], "properties": ["sku"]},
        {"name": "c2", "type": "NODE_PROPERTY_UNIQUENESS", "entityType": "NODE", "labelsOrTypes": ["Category"], "properties": ["category_id"]},
        {"name": "c3", "type": "NODE_KEY", "entityType": "NODE", "labelsOrTypes": ["Order"], "properties": ["tenant_id", "order_id"]},
        {"name": "c4", "type": "NODE_PROPERTY_EXISTENCE", "entityType": "NODE", "labelsOrTypes": ["Product"], "properties": ["title"]},
        {"name": "c5", "type": "RELATIONSHIP_PROPERTY_EXISTENCE", "entityType": "RELATIONSHIP", "labelsOrTypes": ["PART_OF"], "properties": ["depth"]},
    ]
    parsed = parse_constraint_records(rows)
    assert [(c.constraint_type, c.labels, c.properties) for c in parsed] == [
        ("UNIQUENESS", ("Product",), ("sku",)),
        ("UNIQUENESS", ("Category",), ("category_id",)),
        ("NODE_KEY", ("Order",), ("tenant_id", "order_id")),
    ]


def test_naming_sanitization_truncation_and_collisions() -> None:
    assert sanitize_identifier("VIP - Customer") == "VIP___Customer"
    assert sanitize_identifier("123_abc") == "id_123_abc"

    long_raw = "A" * 150
    long_san = sanitize_identifier(long_raw)
    assert len(long_san) == 128
    assert long_san == sanitize_identifier(long_raw)  # deterministic

    with pytest.raises(NamingError, match="reserved keyword"):
        resolve_identifiers([("order", None)], "column", "Product", "nodes.Product.column_renames")

    # Rename resolves reserved word
    resolved = resolve_identifiers([("order", "order_num")], "column", "Product", "nodes.Product.column_renames")
    assert resolved == {"order": "order_num"}

    # Case-insensitive collision fails
    with pytest.raises(NamingError, match="Case-insensitive"):
        resolve_identifiers([("FooBar", None), ("foobar", None)], "column", "T", "sec")


def test_type_classification_and_widening() -> None:
    assert classify_value(True) == "BOOL"
    assert classify_value(42) == "INT64"
    assert classify_value(3.14) == "FLOAT64"
    assert classify_value(["a", "b"]) == "LIST<STRING>"
    assert classify_value([1, 2.5]) == "LIST<FLOAT64>"
    assert classify_value([1, "two"]) == "LIST_MIXED"

    assert widen_types({"INT64": 5}) == ("INT64", False)
    assert widen_types({"INT64": 5, "FLOAT64": 2}) == ("FLOAT64", True)
    assert widen_types({"INT64": 5, "STRING": 1}) == ("STRING(MAX)", True)
    assert widen_types({"LIST<STRING>": 3, "LIST_EMPTY": 1}) == ("ARRAY<STRING(MAX)>", False)
    assert widen_types({"LIST<INT64>": 2, "LIST<STRING>": 1}) == ("JSON", True)
    assert widen_types({"POINT": 1}) == ("JSON", False)
    assert widen_types({"BOOL": 1, "INT64": 1}) == ("STRING(MAX)", True)


def test_bit_reverse_64_bijective() -> None:
    for v in [0, 1, 2, 42, 123456789, (1 << 63) - 1]:
        rev = bit_reverse_64(v)
        assert isinstance(rev, int)
        assert bit_reverse_64(rev) == v
    assert bit_reverse_64(1) != bit_reverse_64(2)


def test_serializer_validation_escaping_and_sentinel() -> None:
    with pytest.raises(SerializerConfigError):
        SerializerConfig(delimiter="|", null_string="a|b")
    with pytest.raises(SerializerConfigError):
        SerializerConfig(delimiter=",", quote_char=",")

    cfg = SerializerConfig(delimiter="|", null_string="__NULL__", quote_char='"', escape_char="\\")
    assert format_field(None, cfg) == "__NULL__"
    assert format_field("", cfg) == '""'
    assert format_field("plain", cfg) == "plain"
    assert format_field('a|b"c\\d\ne\rf', cfg) == '"a|b""c\\\\d\\ne\\rf"'

    with pytest.raises(SentinelCollisionError):
        format_field("__NULL__", cfg, table="Product", column="title", pk="SKU-1")


def test_coerce_temporal_spatial_and_bytes() -> None:
    ny = datetime.datetime(2026, 3, 15, 14, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    assert coerce_value(Neo4jDateTime.from_native(ny), "TIMESTAMP") == "2026-03-15T18:30:00Z"
    assert coerce_value(datetime.datetime(2026, 3, 15, 14, 30, 0), "TIMESTAMP", "UTC") == "2026-03-15T14:30:00Z"
    assert coerce_value(Neo4jDate(2026, 3, 15), "DATE") == "2026-03-15"
    assert coerce_value(Neo4jDuration(days=5), "STRING(MAX)") == "P5D"
    assert coerce_value(b"\x00\x01", "BYTES(MAX)") == "AAE="
    pt_json = coerce_value(CartesianPoint((1.0, 2.0)), "JSON")
    assert json.loads(pt_json) == {"srid": 7203, "x": 1.0, "y": 2.0}


def test_sharded_writer_rotation(tmp_path: Path) -> None:
    cfg = SerializerConfig(delimiter="|")
    with ShardedDelimitedWriter(tmp_path, "nodes", "Product", ["sku", "name"], cfg, chunk_rows=2) as w:
        w.write_row(["S1", "A"])
        w.write_row(["S2", "B"])
        w.write_row(["S3", "C"])
        res = w.close()

    assert res.row_count == 3
    assert len(res.shard_paths) == 2
    assert res.shard_paths[0].read_text(encoding="utf-8") == "S1|A\nS2|B\n"
    assert res.shard_paths[1].read_text(encoding="utf-8") == "S3|C\n"


def test_artifacts_generation(tmp_path: Path) -> None:
    mapping = SchemaMapping(
        version=1,
        neo4j_version="5.23.0",
        neo4j_edition="community",
        nodes={
            "Product": NodeTableMapping(
                raw_label="Product",
                spanner_table="Product",
                pk_columns=["sku"],
                pk_source="uniqueness_constraint",
                properties={
                    "sku": PropertyMapping("sku", "sku", {"STRING": 1}, 0, "STRING(MAX)"),
                    "tags": PropertyMapping("tags", "tags", {"LIST<STRING>": 1}, 0, "ARRAY<STRING(MAX)>"),
                },
            )
        },
        edges={
            "Product__PART_OF__Product": EdgeTripletMapping(
                triplet_key="Product__PART_OF__Product",
                src_label="Product",
                rel_type="PART_OF",
                dst_label="Product",
                spanner_table="Product__PART_OF__Product",
                src_table="Product",
                dst_table="Product",
                has_parallel_edges=True,
                edge_id_column="edge_id",
            )
        },
    )
    cfg = SerializerConfig(delimiter="|")
    generate_artifacts(mapping, tmp_path, "gs://bkt/run1", cfg, emit_unescape=True)

    ddl1 = (tmp_path / "schema/01_create_tables.sql").read_text(encoding="utf-8")
    assert "tags__json JSON" in ddl1
    assert "INTERLEAVE IN PARENT Product ON DELETE CASCADE" in ddl1
    assert "dst_sku STRING(MAX) NOT NULL" in ddl1
    assert "edge_id INT64 NOT NULL" in ddl1

    ddl5 = (tmp_path / "schema/05_property_graph.sql").read_text(encoding="utf-8")
    assert "CREATE OR REPLACE PROPERTY GRAPH MigratedGraph" in ddl5
    assert "LABEL `PART_OF`" in ddl5

    manifest = json.loads((tmp_path / "manifests/nodes_manifest.json").read_text(encoding="utf-8"))
    assert manifest["tables"][0]["columns"][1] == {"column_name": "tags__json", "type_name": "JSON"}
    assert (tmp_path / "schema/03_unescape.sql").exists()
    assert (tmp_path / "load_runbook.sh").exists()
    import subprocess
    subprocess.run(["bash", "-n", str(tmp_path / "load_runbook.sh")], check=True)
