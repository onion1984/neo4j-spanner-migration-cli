"""Parallel per-table Bolt streaming exporter."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import logging
from pathlib import Path
import shutil
from typing import Any

from .artifacts import validate_property_graph_schema
from .compat import cypher_ident, id_expr, label_where_predicate
from .config import EdgeTripletMapping, NodeTableMapping, SchemaMapping, validate_mapping
from .layout import ColumnSpec, get_edge_columns, get_node_columns
from .serializer import EMPTY_BYTES_SENTINEL, SerializerConfig, bit_reverse_64, coerce_value
from .writer import ShardedDelimitedWriter, WriteResult

logger = logging.getLogger(__name__)


@dataclass
class ExportSummary:
    """Results of a full graph export run."""

    nodes: dict[str, WriteResult] = field(default_factory=dict)
    edges: dict[str, WriteResult] = field(default_factory=dict)


def _node_field_value(
    col: ColumnSpec,
    nm: NodeTableMapping,
    props: dict[str, Any],
    lbls: list[str],
    nid: int,
) -> Any:
    if col.role == "pk" and nm.is_synthetic_pk:
        return bit_reverse_64(nid)
    if col.role == "secondary_labels":
        return sorted(l for l in lbls if l != nm.raw_label)
    return props.get(col.raw_name)


def _export_node_table(
    driver: Any,
    database: str,
    nm: NodeTableMapping,
    output_dir: Path,
    serializer_cfg: SerializerConfig,
    chunk_rows: int,
    property_type_overrides: dict[str, str] | None = None,
) -> WriteResult:
    cols = get_node_columns(nm, property_type_overrides)
    col_names = [c.staging_column for c in cols]
    excl = label_where_predicate("n", nm.excluded_labels)
    where_sql = f"WHERE {excl} " if excl else ""
    query = (
        f"MATCH (n:{cypher_ident(nm.raw_label)}) {where_sql}"
        f"RETURN properties(n) AS props, labels(n) AS lbls, {id_expr('n')} AS nid"
    )

    with ShardedDelimitedWriter(
        output_dir=output_dir,
        subdir="nodes",
        table_name=nm.spanner_table,
        columns=col_names,
        serializer_cfg=serializer_cfg,
        chunk_rows=chunk_rows,
    ) as writer:
        with driver.session(database=database) as session:
            for record in session.run(query):
                props = record["props"] or {}
                lbls = list(record["lbls"] or [])
                nid = int(record["nid"])
                pk_vals = []
                row_fields: list[str | None] = []
                for col in cols:
                    raw_val = _node_field_value(col, nm, props, lbls, nid)
                    if col.is_pk:
                        pk_vals.append(raw_val)
                    sentinel = EMPTY_BYTES_SENTINEL if (col.final_type == "BYTES(MAX)" and not col.is_pk) else None
                    coerced = coerce_value(
                        raw_val,
                        col.final_type,
                        serializer_cfg.default_timezone,
                        empty_bytes_sentinel=sentinel,
                    )
                    row_fields.append(coerced)
                writer.write_row(row_fields, pk=tuple(pk_vals))
        result = writer.close()

    logger.info("Exported node table %s: %d rows, %d shard(s)", nm.spanner_table, result.row_count, len(result.shard_paths))
    return result


def _export_edge_table(
    driver: Any,
    database: str,
    em: EdgeTripletMapping,
    src_node: NodeTableMapping,
    dst_node: NodeTableMapping,
    output_dir: Path,
    serializer_cfg: SerializerConfig,
    chunk_rows: int,
    property_type_overrides: dict[str, str] | None = None,
) -> WriteResult:
    cols = get_edge_columns(em, src_node, dst_node, property_type_overrides)
    col_names = [c.staging_column for c in cols]

    src_excl = label_where_predicate("a", src_node.excluded_labels)
    dst_excl = label_where_predicate("b", dst_node.excluded_labels)
    where_parts = [p for p in (src_excl, dst_excl) if p]
    where_sql = f"WHERE {' AND '.join(where_parts)} " if where_parts else ""

    return_items: list[str] = []
    if src_node.is_synthetic_pk:
        return_items.append(f"{id_expr('a')} AS src_nid")
    else:
        for i, pk_raw in enumerate(src_node.pk_columns):
            return_items.append(f"a.{cypher_ident(pk_raw)} AS src_pk_{i}")

    if dst_node.is_synthetic_pk:
        return_items.append(f"{id_expr('b')} AS dst_nid")
    else:
        for i, pk_raw in enumerate(dst_node.pk_columns):
            return_items.append(f"b.{cypher_ident(pk_raw)} AS dst_pk_{i}")

    if em.has_parallel_edges:
        return_items.append(f"{id_expr('r')} AS rid")
    return_items.append("properties(r) AS r_props")

    query = (
        f"MATCH (a:{cypher_ident(em.src_label)})-[r:{cypher_ident(em.rel_type)}]->(b:{cypher_ident(em.dst_label)}) "
        f"{where_sql}"
        f"RETURN {', '.join(return_items)}"
    )

    with ShardedDelimitedWriter(
        output_dir=output_dir,
        subdir="edges",
        table_name=em.spanner_table,
        columns=col_names,
        serializer_cfg=serializer_cfg,
        chunk_rows=chunk_rows,
    ) as writer:
        with driver.session(database=database) as session:
            for record in session.run(query):
                r_props = record["r_props"] or {}
                src_idx = 0
                dst_idx = 0
                pk_vals = []
                row_fields: list[str | None] = []

                for col in cols:
                    if col.role == "src_pk":
                        if src_node.is_synthetic_pk:
                            raw_val = bit_reverse_64(int(record["src_nid"]))
                        else:
                            raw_val = record[f"src_pk_{src_idx}"]
                            src_idx += 1
                    elif col.role == "dst_pk":
                        if dst_node.is_synthetic_pk:
                            raw_val = bit_reverse_64(int(record["dst_nid"]))
                        else:
                            raw_val = record[f"dst_pk_{dst_idx}"]
                            dst_idx += 1
                    elif col.role == "edge_id":
                        raw_val = int(record["rid"])
                    else:
                        raw_val = r_props.get(col.raw_name)

                    if col.is_pk:
                        pk_vals.append(raw_val)
                    sentinel = EMPTY_BYTES_SENTINEL if (col.final_type == "BYTES(MAX)" and not col.is_pk) else None
                    coerced = coerce_value(
                        raw_val,
                        col.final_type,
                        serializer_cfg.default_timezone,
                        empty_bytes_sentinel=sentinel,
                    )
                    row_fields.append(coerced)

                writer.write_row(row_fields, pk=tuple(pk_vals))
        result = writer.close()

    logger.info("Exported edge table %s: %d rows, %d shard(s)", em.spanner_table, result.row_count, len(result.shard_paths))
    return result


def export_graph(
    driver: Any,
    database: str,
    mapping: SchemaMapping,
    output_dir: Path,
    serializer_cfg: SerializerConfig,
    chunk_rows: int = 500_000,
    workers: int = 4,
    overwrite: bool = False,
) -> ExportSummary:
    """Export all node and edge tables in parallel (one streaming cursor per table)."""
    if chunk_rows <= 0:
        raise ValueError(f"chunk_rows must be > 0, got {chunk_rows}")
    if workers <= 0:
        raise ValueError(f"workers must be > 0, got {workers}")
    validate_mapping(mapping)
    validate_property_graph_schema(mapping)

    artifact_subpaths = ("nodes", "edges", "manifests", "schema", "load_runbook.sh")
    existing_artifacts = [p for p in artifact_subpaths if (output_dir / p).exists()]
    if existing_artifacts:
        if not overwrite:
            raise FileExistsError(
                f"Output directory {output_dir} already contains {', '.join(existing_artifacts)}. "
                f"Use a fresh --output-dir or pass --overwrite."
            )
        for p in existing_artifacts:
            target = output_dir / p
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

    summary = ExportSummary()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures: dict[Any, tuple[str, str]] = {}
            for key, nm in mapping.nodes.items():
                fut = pool.submit(
                    _export_node_table,
                    driver,
                    database,
                    nm,
                    output_dir,
                    serializer_cfg,
                    chunk_rows,
                    mapping.property_type_overrides,
                )
                futures[fut] = ("node", key)

            for key, em in mapping.edges.items():
                src_node = mapping.nodes[em.src_label]
                dst_node = mapping.nodes[em.dst_label]
                fut = pool.submit(
                    _export_edge_table,
                    driver,
                    database,
                    em,
                    src_node,
                    dst_node,
                    output_dir,
                    serializer_cfg,
                    chunk_rows,
                    mapping.property_type_overrides,
                )
                futures[fut] = ("edge", key)

            for fut in as_completed(futures):
                kind, key = futures[fut]
                res = fut.result()
                if kind == "node":
                    summary.nodes[key] = res
                else:
                    summary.edges[key] = res
    except BaseException:
        for d in ("nodes", "edges"):
            shutil.rmtree(output_dir / d, ignore_errors=True)
        raise

    return summary
