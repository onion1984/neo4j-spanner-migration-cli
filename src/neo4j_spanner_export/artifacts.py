"""Generate Dataflow manifests, staged Spanner DDL/PDML scripts, and load_runbook.sh."""

from __future__ import annotations

import base64
from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
from typing import TYPE_CHECKING

from .config import EdgeTripletMapping, NodeTableMapping, SchemaMapping, validate_mapping
from .layout import ColumnSpec, get_edge_columns, get_node_columns
from .naming import (
    NamingError,
    derive_prefixed_identifier,
    spanner_backtick,
    validate_gcs_prefix,
    validate_graph_alias,
    validate_identifier,
)
from .serializer import EMPTY_BYTES_SENTINEL, SerializerConfig
from .types import array_element_type

if TYPE_CHECKING:
    from .exporter import ExportSummary


def _pk_ddl_clause(cols: list[ColumnSpec]) -> str:
    pks = [c.staging_column for c in cols if c.is_pk]
    return f"PRIMARY KEY ({', '.join(pks)})"


def _render_create_tables_sql(mapping: SchemaMapping) -> str:
    stmts: list[str] = [
        "-- Stage 01: Create node tables first, then interleaved edge tables.",
        "-- Array columns are staged as <col>__json JSON and converted in Stage 02.",
        "",
    ]

    for nm in mapping.nodes.values():
        cols = get_node_columns(nm, mapping.property_type_overrides)
        col_defs = []
        for c in cols:
            not_null = " NOT NULL" if c.is_pk else ""
            col_defs.append(f"  {c.staging_column} {c.staging_type}{not_null}")
        stmts.append(f"CREATE TABLE {nm.spanner_table} (")
        stmts.append(",\n".join(col_defs))
        stmts.append(f") {_pk_ddl_clause(cols)};")
        stmts.append("")

    for em in mapping.edges.values():
        src_node = mapping.nodes[em.src_label]
        dst_node = mapping.nodes[em.dst_label]
        cols = get_edge_columns(em, src_node, dst_node, mapping.property_type_overrides)
        col_defs = []
        for c in cols:
            not_null = " NOT NULL" if c.is_pk else ""
            col_defs.append(f"  {c.staging_column} {c.staging_type}{not_null}")
        stmts.append(f"CREATE TABLE {em.spanner_table} (")
        stmts.append(",\n".join(col_defs))
        stmts.append(
            f") {_pk_ddl_clause(cols)},\n"
            f"  INTERLEAVE IN PARENT {em.src_table} ON DELETE CASCADE;"
        )
        stmts.append("")

    return "\n".join(stmts)


def _array_conversion_expr(staging_col: str, elem_type: str) -> str:
    """Build a Spanner GoogleSQL expression converting <col>__json into ARRAY<elem_type>."""
    if elem_type in ("STRING", "STRING(MAX)"):
        return f"JSON_VALUE_ARRAY({staging_col})"
    if elem_type == "INT64":
        return f"ARRAY(SELECT CAST(v AS INT64) FROM UNNEST(JSON_VALUE_ARRAY({staging_col})) AS v)"
    if elem_type == "FLOAT64":
        return f"ARRAY(SELECT CAST(v AS FLOAT64) FROM UNNEST(JSON_VALUE_ARRAY({staging_col})) AS v)"
    if elem_type == "BOOL":
        return f"ARRAY(SELECT CAST(v AS BOOL) FROM UNNEST(JSON_VALUE_ARRAY({staging_col})) AS v)"
    raise ValueError(f"Unsupported array element type: {elem_type}")


def _render_arrays_scripts(mapping: SchemaMapping) -> tuple[str, str, str]:
    add_lines = ["-- Stage 02a: Add native ARRAY<T> columns.", ""]
    backfill_lines = ["-- Stage 02b: Backfill ARRAY<T> from <col>__json (run with --enable-partitioned-dml).", ""]
    drop_lines = ["-- Stage 02c: Drop <col>__json staging columns.", ""]

    def _collect(table_name: str, cols: list[ColumnSpec]) -> None:
        arr_cols = [c for c in cols if c.is_array]
        if not arr_cols:
            return
        set_clauses = []
        where_clauses = []
        for c in arr_cols:
            elem = array_element_type(c.final_type)
            add_lines.append(f"ALTER TABLE {table_name} ADD COLUMN {c.spanner_column} {c.final_type};")
            set_clauses.append(f"{c.spanner_column} = {_array_conversion_expr(c.staging_column, elem)}")
            where_clauses.append(f"{c.staging_column} IS NOT NULL")
            drop_lines.append(f"ALTER TABLE {table_name} DROP COLUMN {c.staging_column};")
        backfill_lines.append(
            f"UPDATE {table_name} SET {', '.join(set_clauses)} WHERE {' OR '.join(where_clauses)};"
        )

    for nm in mapping.nodes.values():
        _collect(nm.spanner_table, get_node_columns(nm, mapping.property_type_overrides))
    for em in mapping.edges.values():
        _collect(
            em.spanner_table,
            get_edge_columns(
                em,
                mapping.nodes[em.src_label],
                mapping.nodes[em.dst_label],
                mapping.property_type_overrides,
            ),
        )

    return (
        "\n".join(add_lines) + "\n",
        "\n".join(backfill_lines) + "\n",
        "\n".join(drop_lines) + "\n",
    )


def _render_unescape_sql(mapping: SchemaMapping) -> str:
    """Conditional Stage 03 PDML unescape for STRING(MAX) columns if Dataflow keeps \\n/\\r/\\\\."""
    lines = [
        "-- Stage 03 (conditional): Unescape \\n, \\r, \\\\ in STRING(MAX) columns if Dataflow did not decode them.",
        "-- Run with --enable-partitioned-dml.",
        "",
    ]

    def _unescape_expr(col: str) -> str:
        return (
            f"REPLACE(REPLACE(REPLACE(REPLACE({col}, '\\\\\\\\', '__BSLASH__'), "
            f"'\\\\n', '\\n'), '\\\\r', '\\r'), '__BSLASH__', '\\\\')"
        )

    def _collect(table_name: str, cols: list[ColumnSpec]) -> None:
        str_cols = [c for c in cols if c.final_type == "STRING(MAX)" and not c.is_pk]
        if not str_cols:
            return
        sets = [f"{c.spanner_column} = {_unescape_expr(c.spanner_column)}" for c in str_cols]
        conds = [f"{c.spanner_column} IS NOT NULL" for c in str_cols]
        lines.append(f"UPDATE {table_name} SET {', '.join(sets)} WHERE {' OR '.join(conds)};")

    for nm in mapping.nodes.values():
        _collect(nm.spanner_table, get_node_columns(nm, mapping.property_type_overrides))
    for em in mapping.edges.values():
        _collect(
            em.spanner_table,
            get_edge_columns(
                em,
                mapping.nodes[em.src_label],
                mapping.nodes[em.dst_label],
                mapping.property_type_overrides,
            ),
        )

    return "\n".join(lines) + "\n"


def _render_empty_bytes_sql(mapping: SchemaMapping) -> str:
    """Render Stage 02d PDML to restore empty BYTES(MAX) values from sentinel to b''."""
    b64_sentinel = base64.b64encode(EMPTY_BYTES_SENTINEL).decode("ascii")
    lines = [
        "-- Stage 02d: Restore empty BYTES(MAX) values (b'') from sentinel.",
        "-- Run with --enable-partitioned-dml.",
        "",
    ]

    def _collect(table_name: str, cols: list[ColumnSpec]) -> None:
        bytes_cols = [c for c in cols if c.final_type == "BYTES(MAX)" and not c.is_pk]
        for c in bytes_cols:
            lines.append(
                f"UPDATE {table_name} SET {c.spanner_column} = b'' "
                f"WHERE {c.spanner_column} = FROM_BASE64('{b64_sentinel}');"
            )

    for nm in mapping.nodes.values():
        _collect(nm.spanner_table, get_node_columns(nm, mapping.property_type_overrides))
    for em in mapping.edges.values():
        _collect(
            em.spanner_table,
            get_edge_columns(
                em,
                mapping.nodes[em.src_label],
                mapping.nodes[em.dst_label],
                mapping.property_type_overrides,
            ),
        )

    return "\n".join(lines) + "\n"


def _render_constraints_indexes_sql(mapping: SchemaMapping) -> str:
    lines = [
        "-- Stage 04: Destination Foreign Keys and Reverse-Traversal Secondary Indexes.",
        "",
    ]
    for em in mapping.edges.values():
        src_node = mapping.nodes[em.src_label]
        dst_node = mapping.nodes[em.dst_label]
        cols = get_edge_columns(em, src_node, dst_node, mapping.property_type_overrides)

        src_pk_cols = [c.spanner_column for c in cols if c.role == "src_pk"]
        dst_pk_cols = [c.spanner_column for c in cols if c.role == "dst_pk"]
        dst_ref_cols = [dst_node.properties[pk].spanner_column for pk in dst_node.pk_columns]

        fk_name = derive_prefixed_identifier("fk_", em.spanner_table, "_dst")
        idx_name = derive_prefixed_identifier("idx_", em.spanner_table, "_rev")

        lines.append(
            f"ALTER TABLE {em.spanner_table} ADD CONSTRAINT {fk_name} "
            f"FOREIGN KEY ({', '.join(dst_pk_cols)}) "
            f"REFERENCES {em.dst_table} ({', '.join(dst_ref_cols)});"
        )
        lines.append(
            f"CREATE INDEX {idx_name} ON {em.spanner_table} "
            f"({', '.join(dst_pk_cols + src_pk_cols)});"
        )
        lines.append("")

    return "\n".join(lines)


@dataclass(frozen=True)
class GraphPropertyConflict:
    """A graph-wide (case-insensitive) property name declared with multiple Spanner types."""

    prop_key: str
    display_names: tuple[str, ...]
    occurrences_by_type: dict[str, tuple[str, ...]]


def find_graph_property_conflicts(mapping: SchemaMapping) -> list[GraphPropertyConflict]:
    """Find all property names with conflicting Spanner types across all node and edge tables.

    Spanner Graph evaluates property names case-insensitively in a single graph-wide namespace
    spanning all NODE TABLES and EDGE TABLES.
    """
    by_lower: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    display_names: dict[str, set[str]] = defaultdict(set)

    for nm in mapping.nodes.values():
        for c in get_node_columns(nm, mapping.property_type_overrides):
            prop_alias = nm.column_renames.get(c.raw_name, c.raw_name)
            low = prop_alias.lower()
            display_names[low].add(prop_alias)
            by_lower[low][c.final_type].append(f"node {nm.spanner_table}")

    for em in mapping.edges.values():
        src_node = mapping.nodes[em.src_label]
        dst_node = mapping.nodes[em.dst_label]
        for c in get_edge_columns(em, src_node, dst_node, mapping.property_type_overrides):
            if c.role in ("src_pk", "dst_pk"):
                continue
            prop_alias = em.column_renames.get(c.raw_name, c.raw_name)
            low = prop_alias.lower()
            display_names[low].add(prop_alias)
            by_lower[low][c.final_type].append(f"edge {em.spanner_table}")

    conflicts: list[GraphPropertyConflict] = []
    for low in sorted(by_lower):
        tmap = by_lower[low]
        if len(tmap) > 1:
            conflicts.append(
                GraphPropertyConflict(
                    prop_key=low,
                    display_names=tuple(sorted(display_names[low])),
                    occurrences_by_type={
                        t: tuple(sorted(set(tbls))) for t, tbls in sorted(tmap.items())
                    },
                )
            )
    return conflicts


def _format_table_sample(tables: tuple[str, ...], limit: int = 5) -> str:
    if len(tables) <= limit:
        return ", ".join(tables)
    return f"{', '.join(tables[:limit])}, ... (+{len(tables) - limit} more)"


def validate_property_graph_schema(
    mapping: SchemaMapping,
    graph_name: str = "MigratedGraph",
) -> None:
    """Validate all Spanner CREATE PROPERTY GRAPH invariants before exporting or generating DDL.

    Checks:
    - Property graph identifier validity
    - Graph LABEL and property alias validity
    - Graph-wide case-insensitive property type consistency across ALL node and edge tables
    - Case-insensitive LABEL property signature consistency across node and edge tables
    """
    validate_identifier(graph_name, graph_name, "graph", "property graph", "graph_name")

    # 1. Validate aliases on all nodes and edges
    for nm in mapping.nodes.values():
        validate_graph_alias(
            nm.raw_label,
            kind="LABEL",
            scope=f"node table {nm.spanner_table!r}",
            yaml_hint_section="table_renames",
        )
        for c in get_node_columns(nm, mapping.property_type_overrides):
            prop_alias = nm.column_renames.get(c.raw_name, c.raw_name)
            validate_graph_alias(
                prop_alias,
                kind="property",
                scope=f"node table {nm.spanner_table!r}",
                yaml_hint_section=f"nodes.{nm.raw_label}.column_renames",
            )

    for em in mapping.edges.values():
        validate_graph_alias(
            em.rel_type,
            kind="LABEL",
            scope=f"edge table {em.spanner_table!r}",
            yaml_hint_section="table_renames",
        )
        src_node = mapping.nodes[em.src_label]
        dst_node = mapping.nodes[em.dst_label]
        for c in get_edge_columns(em, src_node, dst_node, mapping.property_type_overrides):
            if c.role in ("src_pk", "dst_pk"):
                continue
            prop_alias = em.column_renames.get(c.raw_name, c.raw_name)
            validate_graph_alias(
                prop_alias,
                kind="property",
                scope=f"edge table {em.spanner_table!r}",
                yaml_hint_section=f"edges.{em.triplet_key}.column_renames",
            )

    # 2. Check graph-wide property type conflicts across ALL node & edge tables (case-insensitive)
    conflicts = find_graph_property_conflicts(mapping)
    if conflicts:
        lines = [
            f"Found {len(conflicts)} graph-wide property(s) with conflicting types across node/edge tables "
            f"(Spanner CREATE PROPERTY GRAPH requires every occurrence of a property name, case-insensitively, "
            f"to share one Spanner type):"
        ]
        for conf in conflicts:
            names_str = "/".join(repr(n) for n in conf.display_names)
            parts = [
                f"{sp_type} ({_format_table_sample(tbls)})"
                for sp_type, tbls in conf.occurrences_by_type.items()
            ]
            lines.append(f"  - {names_str}: {'; '.join(parts)}")
        lines.append(
            "Fix by adding `property_type_overrides` at the top level of schema_mapping.yaml "
            "(e.g. `property_type_overrides: {prop: STRING(MAX)}`), setting per-table `override`s, "
            "or renaming via `column_renames`."
        )
        raise NamingError("\n".join(lines))

    # 3. Check case-insensitive LABEL property signature consistency across nodes & edges
    label_signatures: dict[str, tuple[str, dict[str, str]]] = {}
    for nm in mapping.nodes.values():
        lbl_low = nm.raw_label.lower()
        sig = {
            nm.column_renames.get(c.raw_name, c.raw_name).lower(): c.final_type
            for c in get_node_columns(nm, mapping.property_type_overrides)
        }
        if lbl_low in label_signatures and label_signatures[lbl_low][1] != sig:
            raise NamingError(
                f"Graph LABEL {nm.raw_label!r} is declared multiple times with different property sets."
            )
        label_signatures[lbl_low] = (nm.raw_label, sig)

    edge_label_sigs: dict[str, dict[str, str]] = defaultdict(dict)
    for em in mapping.edges.values():
        lbl_low = em.rel_type.lower()
        src_node = mapping.nodes[em.src_label]
        dst_node = mapping.nodes[em.dst_label]
        for c in get_edge_columns(em, src_node, dst_node, mapping.property_type_overrides):
            if c.role in ("src_pk", "dst_pk"):
                continue
            prop_alias = em.column_renames.get(c.raw_name, c.raw_name)
            edge_label_sigs[lbl_low][prop_alias.lower()] = c.final_type

    for em in mapping.edges.values():
        lbl_low = em.rel_type.lower()
        shared_sig = edge_label_sigs[lbl_low]
        if lbl_low in label_signatures and label_signatures[lbl_low][1] != shared_sig:
            raise NamingError(
                f"Relationship type {em.rel_type!r} shares LABEL {label_signatures[lbl_low][0]!r} with a node label "
                f"but has different properties. Rename the label or relationship type."
            )
        label_signatures[lbl_low] = (em.rel_type, dict(shared_sig))


def _render_property_graph_sql(mapping: SchemaMapping, graph_name: str = "MigratedGraph") -> str:
    validate_property_graph_schema(mapping, graph_name=graph_name)

    node_defs: list[str] = []
    for nm in mapping.nodes.values():
        cols = get_node_columns(nm, mapping.property_type_overrides)
        pk_cols = [c.spanner_column for c in cols if c.is_pk]
        prop_exprs = [
            f"{c.spanner_column} AS {spanner_backtick(nm.column_renames.get(c.raw_name, c.raw_name))}"
            for c in cols
        ]
        node_defs.append(
            f"  {nm.spanner_table}\n"
            f"    KEY ({', '.join(pk_cols)})\n"
            f"    LABEL {spanner_backtick(nm.raw_label)}\n"
            f"    PROPERTIES ({', '.join(prop_exprs)})"
        )

    # Group edge properties by rel_type (case-insensitive) so polymorphic tables sharing a LABEL
    # declare the exact same set of property names (casting missing columns to NULL).
    label_prop_types: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
    for em in mapping.edges.values():
        lbl_low = em.rel_type.lower()
        src_node = mapping.nodes[em.src_label]
        dst_node = mapping.nodes[em.dst_label]
        for c in get_edge_columns(em, src_node, dst_node, mapping.property_type_overrides):
            if c.role in ("src_pk", "dst_pk"):
                continue
            prop_alias = em.column_renames.get(c.raw_name, c.raw_name)
            prop_low = prop_alias.lower()
            if prop_low not in label_prop_types[lbl_low]:
                label_prop_types[lbl_low][prop_low] = (prop_alias, c.final_type)

    edge_defs: list[str] = []
    for em in mapping.edges.values():
        src_node = mapping.nodes[em.src_label]
        dst_node = mapping.nodes[em.dst_label]
        cols = get_edge_columns(em, src_node, dst_node, mapping.property_type_overrides)
        pk_cols = [c.spanner_column for c in cols if c.is_pk]
        src_pk_cols = [c.spanner_column for c in cols if c.role == "src_pk"]
        dst_pk_cols = [c.spanner_column for c in cols if c.role == "dst_pk"]
        src_ref_cols = [src_node.properties[pk].spanner_column for pk in src_node.pk_columns]
        dst_ref_cols = [dst_node.properties[pk].spanner_column for pk in dst_node.pk_columns]

        cols_by_alias_lower = {
            em.column_renames.get(c.raw_name, c.raw_name).lower(): c
            for c in cols
            if c.role not in ("src_pk", "dst_pk")
        }
        shared_props = label_prop_types[em.rel_type.lower()]

        if shared_props:
            prop_exprs = []
            for prop_low in sorted(shared_props):
                canonical_alias, target_type = shared_props[prop_low]
                if prop_low in cols_by_alias_lower:
                    c = cols_by_alias_lower[prop_low]
                    prop_exprs.append(f"{c.spanner_column} AS {spanner_backtick(canonical_alias)}")
                else:
                    prop_exprs.append(f"CAST(NULL AS {target_type}) AS {spanner_backtick(canonical_alias)}")
            props_clause = f"PROPERTIES ({', '.join(prop_exprs)})"
        else:
            props_clause = "NO PROPERTIES"

        edge_defs.append(
            f"  {em.spanner_table}\n"
            f"    KEY ({', '.join(pk_cols)})\n"
            f"    SOURCE KEY ({', '.join(src_pk_cols)}) REFERENCES {em.src_table} ({', '.join(src_ref_cols)})\n"
            f"    DESTINATION KEY ({', '.join(dst_pk_cols)}) REFERENCES {em.dst_table} ({', '.join(dst_ref_cols)})\n"
            f"    LABEL {spanner_backtick(em.rel_type)}\n"
            f"    {props_clause}"
        )

    parts = [
        f"-- Stage 05: Create Spanner Property Graph `{graph_name}`.",
        f"CREATE OR REPLACE PROPERTY GRAPH {graph_name}",
        "NODE TABLES (",
        ",\n".join(node_defs),
        ")",
    ]
    if edge_defs:
        parts.extend(["EDGE TABLES (", ",\n".join(edge_defs), ")"])
    parts.append(";")
    return "\n".join(parts) + "\n"


def _build_manifest(
    tables: list[tuple[str, list[ColumnSpec]]],
    gcs_prefix: str,
    subdir: str,
    shard_map: dict[str, list[Path]] | None = None,
) -> dict[str, object]:
    prefix = gcs_prefix.rstrip("/")
    entries = []
    for table_name, cols in tables:
        if shard_map is not None:
            shards = shard_map.get(table_name, [])
            if not shards:
                # Omit 0-row tables so Dataflow never fails on an unmatched glob.
                continue
            patterns = [f"{prefix}/{subdir}/{p.name}" for p in shards]
        else:
            patterns = [f"{prefix}/{subdir}/{table_name}_part_*.csv"]
        entries.append(
            {
                "table_name": table_name,
                "file_patterns": patterns,
                "columns": [
                    {"column_name": c.staging_column, "type_name": c.manifest_type}
                    for c in cols
                ],
            }
        )
    return {"tables": entries}


def _bash_dq_escape(val: str) -> str:
    """Escape a literal value for inclusion inside a bash double-quoted string."""
    return val.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")


def _pick_param_sep(values: list[str]) -> str:
    """Pick a gcloud --parameters ^<sep>^ separator that does not appear in any parameter value."""
    for sep in ("~", "|", ";", "#", "@", "!", ":"):
        if all(sep not in v for v in values):
            return sep
    raise NamingError(
        "Cannot find a safe gcloud --parameters separator for the configured delimiter/null-string/quote/escape."
    )


def _render_load_runbook(
    gcs_prefix: str,
    serializer_cfg: SerializerConfig,
    emit_unescape: bool,
    has_edges: bool = True,
) -> str:
    # Dataflow GCS_Text_to_Cloud_Spanner expects a literal 1-char delimiter; splice $'\t' in bash for tab.
    raw_delim = serializer_cfg.delimiter
    sep = _pick_param_sep(
        [
            raw_delim,
            serializer_cfg.quote_char,
            serializer_cfg.escape_char,
            serializer_cfg.null_string,
            gcs_prefix,
        ]
    )
    delim = "\"$'\\t'\"" if raw_delim == "\t" else _bash_dq_escape(raw_delim)
    quote_esc = _bash_dq_escape(serializer_cfg.quote_char)
    escape_esc = _bash_dq_escape(serializer_cfg.escape_char)
    null_esc = _bash_dq_escape(serializer_cfg.null_string)

    unescape_block = (
        'if [[ "${SKIP_STAGE_03:-false}" != "true" ]] && grep -q "UPDATE " "${SCRIPT_DIR}/schema/03_unescape.sql"; then\n'
        '  run_pdml_file "${SCRIPT_DIR}/schema/03_unescape.sql"\n'
        'fi\n'
        if emit_unescape
        else '# Optional Stage 03 (schema/03_unescape.sql) not enabled; pass --emit-unescape if needed.\n'
    )

    edges_upload_block = (
        '  if [[ -d "${SCRIPT_DIR}/edges" ]] && compgen -G "${SCRIPT_DIR}/edges/*.csv" >/dev/null; then\n'
        '    gcloud storage rm --recursive "${GCS_PREFIX}/edges/**" --project="${PROJECT_ID}" --quiet 2>/dev/null || true\n'
        '    gcloud storage cp --recursive "${SCRIPT_DIR}/edges" "${GCS_PREFIX}/" --project="${PROJECT_ID}" --quiet\n'
        '  fi\n'
        if has_edges
        else '  # No edge tables in schema_mapping.yaml; skipping edges/ upload.\n'
    )

    edges_job_block = (
        f'echo "=== 4. Run Dataflow job 2 (Edges) ==="\n'
        f'if [[ "${{SKIP_DATAFLOW:-false}}" != "true" ]] && grep -q \'"table_name"\' "${{SCRIPT_DIR}}/manifests/edges_manifest.json"; then\n'
        f'  EDGES_JOB=$(gcloud dataflow jobs run "neo4j-load-edges-$$-${{RANDOM}}-$(date +%s)" \\\n'
        f'    --gcs-location="gs://dataflow-templates-${{DATAFLOW_REGION}}/latest/GCS_Text_to_Cloud_Spanner" \\\n'
        f'    --region="${{DATAFLOW_REGION}}" \\\n'
        f'    --project="${{PROJECT_ID}}" \\\n'
        f'    "${{EXTRA_DF_FLAGS[@]}}" \\\n'
        f'    --parameters="^{sep}^instanceId=${{INSTANCE}}{sep}databaseId=${{DATABASE}}{sep}importManifest=${{GCS_PREFIX}}/manifests/edges_manifest.json{sep}columnDelimiter={delim}{sep}fieldQualifier={quote_esc}{sep}escape={escape_esc}{sep}nullString={null_esc}{sep}trailingDelimiter=false{sep}invalidOutputPath=${{GCS_PREFIX}}/invalid_records/edges" \\\n'
        f'    --format="value(id)" \\\n'
        f'    --quiet)\n'
        f'  echo "Edges Dataflow Job ID: ${{EDGES_JOB}}"\n'
        f'  wait_for_job "${{EDGES_JOB}}"\n'
        f'  check_invalid_records "${{GCS_PREFIX}}/invalid_records/edges"\n'
        f'else\n'
        f'  echo "Skipping Edges Dataflow job (no edge shards or SKIP_DATAFLOW=true)."\n'
        f'fi\n'
        if has_edges
        else 'echo "=== 4. Skip Dataflow job 2 (Edges: no edge tables) ==="\n'
    )

    return f"""#!/usr/bin/env bash
set -euo pipefail

# Neo4j -> Cloud Spanner Graph load runbook
# Review and set the target variables below before running.
# Resume / idempotency env flags: SKIP_DB_CREATE, SKIP_UPLOAD, SKIP_DATAFLOW, SKIP_STAGE_02, SKIP_STAGE_03, SKIP_STAGE_04, SKIP_STAGE_05
PROJECT_ID="${{PROJECT_ID:-YOUR_PROJECT_ID}}"
INSTANCE="${{INSTANCE:-YOUR_SPANNER_INSTANCE}}"
DATABASE="${{DATABASE:-neo4j_graph}}"
REGION="${{REGION:-us-central1}}"
DATAFLOW_REGION="${{DATAFLOW_REGION:-${{REGION}}}}"
DATAFLOW_SUBNETWORK="${{DATAFLOW_SUBNETWORK:-}}"
DATAFLOW_DISABLE_PUBLIC_IPS="${{DATAFLOW_DISABLE_PUBLIC_IPS:-false}}"
GCS_PREFIX="${{GCS_PREFIX:-{gcs_prefix.rstrip('/')}}}"

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"

EXTRA_DF_FLAGS=()
if [[ -n "${{DATAFLOW_SUBNETWORK}}" ]]; then
  EXTRA_DF_FLAGS+=("--subnetwork=${{DATAFLOW_SUBNETWORK}}")
fi
if [[ "${{DATAFLOW_DISABLE_PUBLIC_IPS}}" == "true" ]]; then
  EXTRA_DF_FLAGS+=("--disable-public-ips")
fi

run_pdml_file() {{
  local sql_file="$1"
  while IFS= read -r stmt; do
    [[ -z "${{stmt}}" || "${{stmt}}" == --* ]] && continue
    gcloud spanner databases execute-sql "${{DATABASE}}" \\
      --instance="${{INSTANCE}}" --project="${{PROJECT_ID}}" \\
      --enable-partitioned-dml --sql="${{stmt}}" --quiet
  done < "${{sql_file}}"
}}

wait_for_job() {{
  local job_id="$1"
  while true; do
    state=$(gcloud dataflow jobs describe "${{job_id}}" --region="${{DATAFLOW_REGION}}" --project="${{PROJECT_ID}}" --format="value(currentState)" --quiet)
    echo "Job ${{job_id}} state: ${{state}}"
    case "${{state}}" in
      JOB_STATE_DONE) return 0 ;;
      JOB_STATE_FAILED|JOB_STATE_CANCELLED|JOB_STATE_DRAINED) echo "Job failed: ${{state}}" >&2; return 1 ;;
    esac
    sleep 20
  done
}}

check_invalid_records() {{
  local invalid_prefix="$1"
  local invalid_files
  invalid_files=$(gcloud storage ls "${{invalid_prefix}}/**" --project="${{PROJECT_ID}}" 2>/dev/null || true)
  if [[ -n "${{invalid_files}}" ]]; then
    echo "ERROR: Dataflow rejected rows written to ${{invalid_prefix}}:" >&2
    echo "${{invalid_files}}" >&2
    return 1
  fi
}}

echo "=== 1. Create Spanner database with Stage 01 DDL (idempotent) ==="
if [[ "${{SKIP_DB_CREATE:-false}}" != "true" ]]; then
  if gcloud spanner databases describe "${{DATABASE}}" --instance="${{INSTANCE}}" --project="${{PROJECT_ID}}" >/dev/null 2>&1; then
    echo "Database ${{DATABASE}} already exists; skipping creation."
  else
    gcloud spanner databases create "${{DATABASE}}" \\
      --instance="${{INSTANCE}}" \\
      --project="${{PROJECT_ID}}" \\
      --ddl-file="${{SCRIPT_DIR}}/schema/01_create_tables.sql" \\
      --quiet
  fi
fi

echo "=== 2. Upload CSV shards and manifests to GCS ==="
if [[ "${{SKIP_UPLOAD:-false}}" != "true" ]]; then
  gcloud storage rm --recursive "${{GCS_PREFIX}}/nodes/**" "${{GCS_PREFIX}}/manifests/**" --project="${{PROJECT_ID}}" --quiet 2>/dev/null || true
  if [[ -d "${{SCRIPT_DIR}}/nodes" ]] && compgen -G "${{SCRIPT_DIR}}/nodes/*.csv" >/dev/null; then
    gcloud storage cp --recursive "${{SCRIPT_DIR}}/nodes" "${{GCS_PREFIX}}/" --project="${{PROJECT_ID}}" --quiet
  fi
{edges_upload_block}  gcloud storage cp --recursive "${{SCRIPT_DIR}}/manifests" "${{GCS_PREFIX}}/" --project="${{PROJECT_ID}}" --quiet
fi

echo "=== 3. Run Dataflow job 1 (Nodes) ==="
if [[ "${{SKIP_DATAFLOW:-false}}" != "true" ]] && grep -q '"table_name"' "${{SCRIPT_DIR}}/manifests/nodes_manifest.json"; then
  NODES_JOB=$(gcloud dataflow jobs run "neo4j-load-nodes-$$-${{RANDOM}}-$(date +%s)" \\
    --gcs-location="gs://dataflow-templates-${{DATAFLOW_REGION}}/latest/GCS_Text_to_Cloud_Spanner" \\
    --region="${{DATAFLOW_REGION}}" \\
    --project="${{PROJECT_ID}}" \\
    "${{EXTRA_DF_FLAGS[@]}}" \\
    --parameters="^{sep}^instanceId=${{INSTANCE}}{sep}databaseId=${{DATABASE}}{sep}importManifest=${{GCS_PREFIX}}/manifests/nodes_manifest.json{sep}columnDelimiter={delim}{sep}fieldQualifier={quote_esc}{sep}escape={escape_esc}{sep}nullString={null_esc}{sep}trailingDelimiter=false{sep}invalidOutputPath=${{GCS_PREFIX}}/invalid_records/nodes" \\
    --format="value(id)" \\
    --quiet)
  echo "Nodes Dataflow Job ID: ${{NODES_JOB}}"
  wait_for_job "${{NODES_JOB}}"
  check_invalid_records "${{GCS_PREFIX}}/invalid_records/nodes"
else
  echo "Skipping Nodes Dataflow job (no node shards or SKIP_DATAFLOW=true)."
fi

{edges_job_block}
echo "=== 5. Stage 02: Convert staged JSON arrays to native ARRAY<T> & restore empty BYTES ==="
if [[ "${{SKIP_STAGE_02:-false}}" != "true" ]] && grep -q "ALTER TABLE" "${{SCRIPT_DIR}}/schema/02_arrays_add.sql"; then
  gcloud spanner databases ddl update "${{DATABASE}}" \\
    --instance="${{INSTANCE}}" --project="${{PROJECT_ID}}" \\
    --ddl-file="${{SCRIPT_DIR}}/schema/02_arrays_add.sql" --quiet

  run_pdml_file "${{SCRIPT_DIR}}/schema/02_arrays_backfill.sql"

  gcloud spanner databases ddl update "${{DATABASE}}" \\
    --instance="${{INSTANCE}}" --project="${{PROJECT_ID}}" \\
    --ddl-file="${{SCRIPT_DIR}}/schema/02_arrays_drop.sql" --quiet
fi
if [[ "${{SKIP_STAGE_02:-false}}" != "true" ]] && [[ -f "${{SCRIPT_DIR}}/schema/02d_empty_bytes.sql" ]] && grep -q "UPDATE " "${{SCRIPT_DIR}}/schema/02d_empty_bytes.sql"; then
  run_pdml_file "${{SCRIPT_DIR}}/schema/02d_empty_bytes.sql"
fi

echo "=== 6. Stage 03: Conditional unescape ==="
{unescape_block}
echo "=== 7. Stage 04: Destination FKs & reverse-traversal indexes ==="
if [[ "${{SKIP_STAGE_04:-false}}" != "true" ]] && grep -q "ALTER TABLE\\|CREATE INDEX" "${{SCRIPT_DIR}}/schema/04_constraints_indexes.sql"; then
  gcloud spanner databases ddl update "${{DATABASE}}" \\
    --instance="${{INSTANCE}}" --project="${{PROJECT_ID}}" \\
    --ddl-file="${{SCRIPT_DIR}}/schema/04_constraints_indexes.sql" --quiet
fi

echo "=== 8. Stage 05: Create Spanner Property Graph ==="
if [[ "${{SKIP_STAGE_05:-false}}" != "true" ]]; then
  gcloud spanner databases ddl update "${{DATABASE}}" \\
    --instance="${{INSTANCE}}" --project="${{PROJECT_ID}}" \\
    --ddl-file="${{SCRIPT_DIR}}/schema/05_property_graph.sql" --quiet
fi

echo "=== Load complete! ==="
"""


def generate_artifacts(
    mapping: SchemaMapping,
    output_dir: Path,
    gcs_prefix: str,
    serializer_cfg: SerializerConfig,
    graph_name: str = "MigratedGraph",
    emit_unescape: bool = False,
    summary: ExportSummary | None = None,
) -> None:
    """Write all staged SQL files, Dataflow manifests, and load_runbook.sh."""
    validate_mapping(mapping)
    validate_gcs_prefix(gcs_prefix)
    validate_identifier(graph_name, graph_name, "graph", "property graph", "graph_name")

    schema_dir = output_dir / "schema"
    manifests_dir = output_dir / "manifests"
    schema_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    (schema_dir / "01_create_tables.sql").write_text(
        _render_create_tables_sql(mapping), encoding="utf-8"
    )

    add_sql, backfill_sql, drop_sql = _render_arrays_scripts(mapping)
    (schema_dir / "02_arrays_add.sql").write_text(add_sql, encoding="utf-8")
    (schema_dir / "02_arrays_backfill.sql").write_text(backfill_sql, encoding="utf-8")
    (schema_dir / "02_arrays_drop.sql").write_text(drop_sql, encoding="utf-8")
    (schema_dir / "02d_empty_bytes.sql").write_text(
        _render_empty_bytes_sql(mapping), encoding="utf-8"
    )

    if emit_unescape:
        (schema_dir / "03_unescape.sql").write_text(
            _render_unescape_sql(mapping), encoding="utf-8"
        )

    (schema_dir / "04_constraints_indexes.sql").write_text(
        _render_constraints_indexes_sql(mapping), encoding="utf-8"
    )
    (schema_dir / "05_property_graph.sql").write_text(
        _render_property_graph_sql(mapping, graph_name=graph_name), encoding="utf-8"
    )

    node_tables = [
        (nm.spanner_table, get_node_columns(nm, mapping.property_type_overrides))
        for nm in mapping.nodes.values()
    ]
    edge_tables = [
        (
            em.spanner_table,
            get_edge_columns(
                em,
                mapping.nodes[em.src_label],
                mapping.nodes[em.dst_label],
                mapping.property_type_overrides,
            ),
        )
        for em in mapping.edges.values()
    ]

    node_shards = (
        {r.table_name: r.shard_paths for r in summary.nodes.values()}
        if summary is not None
        else None
    )
    edge_shards = (
        {r.table_name: r.shard_paths for r in summary.edges.values()}
        if summary is not None
        else None
    )

    (manifests_dir / "nodes_manifest.json").write_text(
        json.dumps(_build_manifest(node_tables, gcs_prefix, "nodes", shard_map=node_shards), indent=2) + "\n",
        encoding="utf-8",
    )
    (manifests_dir / "edges_manifest.json").write_text(
        json.dumps(_build_manifest(edge_tables, gcs_prefix, "edges", shard_map=edge_shards), indent=2) + "\n",
        encoding="utf-8",
    )

    runbook_path = output_dir / "load_runbook.sh"
    runbook_path.write_text(
        _render_load_runbook(
            gcs_prefix,
            serializer_cfg,
            emit_unescape=emit_unescape,
            has_edges=bool(mapping.edges),
        ),
        encoding="utf-8",
    )
    runbook_path.chmod(0o755)
