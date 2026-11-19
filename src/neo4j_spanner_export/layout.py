"""Shared column layout contract used by exporter, artifacts generator, and verifier."""

from __future__ import annotations

from dataclasses import dataclass

from .config import EdgeTripletMapping, NodeTableMapping
from .naming import derive_prefixed_identifier
from .types import (
    is_array_type,
    manifest_type_name,
    staging_column_name,
    staging_spanner_type,
)


@dataclass(frozen=True)
class ColumnSpec:
    """Resolved column specification for CSV, DDL, manifest, and verification."""

    raw_name: str           # Neo4j property name (or '_neo4j_id', 'secondary_labels', 'edge_id')
    spanner_column: str     # Final Spanner column name
    staging_column: str     # CSV / 01 DDL / manifest column name (<col>__json for arrays)
    final_type: str         # Final Spanner type (e.g. ARRAY<STRING>, INT64, STRING(MAX))
    staging_type: str       # 01 DDL type (JSON for arrays)
    manifest_type: str      # Dataflow manifest type_name (STRING, BYTES, INT64, ...)
    is_pk: bool = False
    is_array: bool = False
    role: str = "prop"      # "pk" | "src_pk" | "dst_pk" | "edge_id" | "secondary_labels" | "prop"
    source_raw_name: str = ""  # For src_pk / dst_pk: the node's raw PK property name


def get_node_columns(nm: NodeTableMapping) -> list[ColumnSpec]:
    """Return the ordered list of ColumnSpecs for a node table."""
    cols: list[ColumnSpec] = []
    pk_set = set(nm.pk_columns)

    for pk_raw in nm.pk_columns:
        pm = nm.properties[pk_raw]
        eff = pm.effective_type
        cols.append(
            ColumnSpec(
                raw_name=pk_raw,
                spanner_column=pm.spanner_column,
                staging_column=staging_column_name(pm.spanner_column, eff),
                final_type=eff,
                staging_type=staging_spanner_type(eff),
                manifest_type=manifest_type_name(eff),
                is_pk=True,
                is_array=is_array_type(eff),
                role="pk",
                source_raw_name=pk_raw,
            )
        )

    for raw_name in sorted(nm.properties):
        if raw_name in pk_set:
            continue
        pm = nm.properties[raw_name]
        eff = pm.effective_type
        role = "secondary_labels" if raw_name == "secondary_labels" else "prop"
        cols.append(
            ColumnSpec(
                raw_name=raw_name,
                spanner_column=pm.spanner_column,
                staging_column=staging_column_name(pm.spanner_column, eff),
                final_type=eff,
                staging_type=staging_spanner_type(eff),
                manifest_type=manifest_type_name(eff),
                is_pk=False,
                is_array=is_array_type(eff),
                role=role,
            )
        )

    return cols


def get_edge_columns(
    em: EdgeTripletMapping,
    src_node: NodeTableMapping,
    dst_node: NodeTableMapping,
) -> list[ColumnSpec]:
    """Return the ordered list of ColumnSpecs for an edge triplet table."""
    cols: list[ColumnSpec] = []

    for pk_raw in src_node.pk_columns:
        pm = src_node.properties[pk_raw]
        eff = pm.effective_type
        cols.append(
            ColumnSpec(
                raw_name=pm.spanner_column,
                spanner_column=pm.spanner_column,
                staging_column=pm.spanner_column,
                final_type=eff,
                staging_type=staging_spanner_type(eff),
                manifest_type=manifest_type_name(eff),
                is_pk=True,
                is_array=False,
                role="src_pk",
                source_raw_name=pk_raw,
            )
        )

    for pk_raw in dst_node.pk_columns:
        pm = dst_node.properties[pk_raw]
        eff = pm.effective_type
        dst_col = derive_prefixed_identifier("dst_", pm.spanner_column)
        cols.append(
            ColumnSpec(
                raw_name=dst_col,
                spanner_column=dst_col,
                staging_column=dst_col,
                final_type=eff,
                staging_type=staging_spanner_type(eff),
                manifest_type=manifest_type_name(eff),
                is_pk=True,
                is_array=False,
                role="dst_pk",
                source_raw_name=pk_raw,
            )
        )

    if em.has_parallel_edges:
        eid_col = em.edge_id_column or "edge_id"
        cols.append(
            ColumnSpec(
                raw_name=eid_col,
                spanner_column=eid_col,
                staging_column=eid_col,
                final_type="INT64",
                staging_type="INT64",
                manifest_type="INT64",
                is_pk=True,
                is_array=False,
                role="edge_id",
            )
        )

    for raw_name in sorted(em.properties):
        pm = em.properties[raw_name]
        eff = pm.effective_type
        cols.append(
            ColumnSpec(
                raw_name=raw_name,
                spanner_column=pm.spanner_column,
                staging_column=staging_column_name(pm.spanner_column, eff),
                final_type=eff,
                staging_type=staging_spanner_type(eff),
                manifest_type=manifest_type_name(eff),
                is_pk=False,
                is_array=is_array_type(eff),
                role="prop",
            )
        )

    return cols
