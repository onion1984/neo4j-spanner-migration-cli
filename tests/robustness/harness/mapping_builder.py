"""Build small SchemaMapping objects for offline (T0) artifact tests."""

from __future__ import annotations

from neo4j_spanner_export.config import EdgeTripletMapping, NodeTableMapping, PropertyMapping, SchemaMapping


def prop(name: str, typ: str = "STRING(MAX)", col: str | None = None, override: str | None = None) -> PropertyMapping:
    return PropertyMapping(raw_name=name, spanner_column=col or name, observed={}, resolved=typ, override=override)


def node(label: str, pk: list[str], props: dict[str, str], table: str | None = None) -> NodeTableMapping:
    return NodeTableMapping(
        raw_label=label,
        spanner_table=table or label,
        pk_columns=pk,
        pk_source="uniqueness_constraint",
        properties={k: prop(k, v) for k, v in props.items()},
    )


def edge(src: NodeTableMapping, rel: str, dst: NodeTableMapping, props: dict[str, str] | None = None,
         table: str | None = None, parallel: bool = False) -> EdgeTripletMapping:
    key = f"{src.raw_label}__{rel}__{dst.raw_label}"
    return EdgeTripletMapping(
        triplet_key=key,
        src_label=src.raw_label,
        rel_type=rel,
        dst_label=dst.raw_label,
        spanner_table=table or key,
        src_table=src.spanner_table,
        dst_table=dst.spanner_table,
        has_parallel_edges=parallel,
        edge_id_column="edge_id" if parallel else None,
        properties={k: prop(k, v) for k, v in (props or {}).items()},
    )


def mapping(nodes: list[NodeTableMapping], edges: list[EdgeTripletMapping] | None = None) -> SchemaMapping:
    return SchemaMapping(nodes={n.raw_label: n for n in nodes}, edges={e.triplet_key: e for e in (edges or [])})
