"""Integration tests against local Neo4j 4.4 and 5.x Community containers."""

from __future__ import annotations

import os
from pathlib import Path

from neo4j import GraphDatabase
import pytest

from neo4j_spanner_export.artifacts import generate_artifacts
from neo4j_spanner_export.config import SchemaMapping, save_mapping
from neo4j_spanner_export.discovery import DiscoveryError, discover_schema
from neo4j_spanner_export.exporter import export_graph
from neo4j_spanner_export.naming import NamingError
from neo4j_spanner_export.serializer import SerializerConfig

pytestmark = pytest.mark.skipif(
    os.environ.get("NEO4J_INTEGRATION") != "1",
    reason="Set NEO4J_INTEGRATION=1 to run against local Neo4j 4.4 and 5.x containers",
)

V5_URI = os.environ.get("NEO4J_V5_URI", "bolt://localhost:7687")
V4_URI = os.environ.get("NEO4J_V4_URI", "bolt://localhost:7688")
PW = os.environ.get("NEO4J_PASSWORD", "testpassword123")


def _base_input_mapping(path: Path) -> Path:
    m = SchemaMapping(
        label_priority=["Product", "Category", "Service", "Account", "Order", "AuditNote"],
        pk_overrides={"Order": ["tenant_id", "order_id"]},
    )
    save_mapping(m, path)
    return path


def test_ambiguous_multilabel_fails_fast(tmp_path: Path) -> None:
    from scripts.seed_synthetic_graph import seed_graph

    seed_graph(V5_URI, "neo4j", PW, "neo4j", include_ambiguous=True)
    in_map = _base_input_mapping(tmp_path / "in.yaml")
    with GraphDatabase.driver(V5_URI, auth=("neo4j", PW)) as driver:
        with pytest.raises(DiscoveryError, match="AmbigA.*AmbigB"):
            discover_schema(driver, "neo4j", tmp_path / "out.yaml", input_mapping_path=in_map)


def test_v4_and_v5_parity_export(tmp_path: Path) -> None:
    from scripts.seed_synthetic_graph import seed_graph

    bundles: dict[str, Path] = {}
    for ver, uri in [("v5", V5_URI), ("v4", V4_URI)]:
        seed_graph(uri, "neo4j", PW, "neo4j", include_ambiguous=False)
        bdir = tmp_path / ver
        bdir.mkdir()
        in_map = _base_input_mapping(bdir / "in.yaml")

        # First discovery hits reserved word `order` on Product -> verify NamingError
        with GraphDatabase.driver(uri, auth=("neo4j", PW)) as driver:
            with pytest.raises(NamingError, match="reserved keyword"):
                discover_schema(driver, "neo4j", bdir / "schema_mapping.yaml", input_mapping_path=in_map)

            # Add renames for `order` -> `order_num` and `Order` -> `Orders` and re-run
            m = SchemaMapping(
                label_priority=["Product", "Category", "Service", "Account", "Order", "AuditNote"],
                table_renames={"Order": "Orders"},
                pk_overrides={"Order": ["tenant_id", "order_id"]},
            )
            from neo4j_spanner_export.config import NodeTableMapping

            m.nodes["Product"] = NodeTableMapping(
                raw_label="Product",
                spanner_table="Product",
                pk_columns=["sku"],
                pk_source="uniqueness_constraint",
                column_renames={"order": "order_num"},
            )
            save_mapping(m, in_map)

            mapping = discover_schema(
                driver,
                "neo4j",
                bdir / "schema_mapping.yaml",
                input_mapping_path=in_map,
                report_path=bdir / "discovery_report.md",
            )
            cfg = SerializerConfig(delimiter="|")
            summary = export_graph(driver, "neo4j", mapping, bdir / "export_out", cfg, chunk_rows=1, workers=2)
            generate_artifacts(mapping, bdir / "export_out", "gs://test-bkt/run", cfg)
            bundles[ver] = bdir

            assert summary.nodes["Product"].row_count == 2
            assert summary.edges["Account__TRANSFERRED__Account"].row_count == 2
            assert mapping.edges["Account__TRANSFERRED__Account"].has_parallel_edges is True
            assert mapping.nodes["AuditNote"].is_synthetic_pk is True
            assert mapping.nodes["Order"].pk_columns == ["tenant_id", "order_id"]

    # Compare 4.4 and 5.x DDL and node/edge row counts
    v5_ddl = (bundles["v5"] / "export_out/schema/01_create_tables.sql").read_text()
    v4_ddl = (bundles["v4"] / "export_out/schema/01_create_tables.sql").read_text()
    assert v5_ddl == v4_ddl

    # Compare Product CSVs (business PKs, identical data)
    v5_prod = sorted((bundles["v5"] / "export_out/nodes").glob("Product_part_*.csv"))
    v4_prod = sorted((bundles["v4"] / "export_out/nodes").glob("Product_part_*.csv"))
    assert len(v5_prod) == len(v4_prod) == 2  # chunk_rows=1 -> 2 shards
    v5_lines = sorted(p.read_text() for p in v5_prod)
    v4_lines = sorted(p.read_text() for p in v4_prod)
    assert v5_lines == v4_lines
