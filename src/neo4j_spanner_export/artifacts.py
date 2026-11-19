"""Generate Dataflow manifests, staged Spanner DDL/PDML scripts, and load_runbook.sh."""

from __future__ import annotations

import base64
from collections import defaultdict
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
from .types import array_element_type, is_array_type

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
        cols = get_node_columns(nm)
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
        cols = get_edge_columns(em, src_node, dst_node)
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
        _collect(nm.spanner_table, get_node_columns(nm))
    for em in mapping.edges.values():
        _collect(em.spanner_table, get_edge_columns(em, mapping.nodes[em.src_label], mapping.nodes[em.dst_label]))

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
        _collect(nm.spanner_table, get_node_columns(nm))
    for em in mapping.edges.values():
        _collect(em.spanner_table, get_edge_columns(em, mapping.nodes[em.src_label], mapping.nodes[em.dst_label]))

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
        _collect(nm.spanner_table, get_node_columns(nm))
    for em in mapping.edges.values():
        _collect(em.spanner_table, get_edge_columns(em, mapping.nodes[em.src_label], mapping.nodes[em.dst_label]))

    return "\n".join(lines) + "\n"


def _render_constraints_indexes_sql(mapping: SchemaMapping) -> str:
    lines = [
        "-- Stage 04: Destination Foreign Keys and Reverse-Traversal Secondary Indexes.",
        "",
    ]
    for em in mapping.edges.values():
        src_node = mapping.nodes[em.src_label]
        dst_node = mapping.nodes[em.dst_label]
        cols = get_edge_columns(em, src_node, dst_node)

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


def _can_cast_in_graph_ddl(src_type: str, dst_type: str) -> bool:
    """Return True if Spanner Graph DDL supports CAST(col AS dst_type) from src_type."""
    if src_type == dst_type:
        return True
    if is_array_type(src_type) or src_type == "JSON":
        return False
    if {src_type, dst_type} == {"INT64", "FLOAT64"}:
        return dst_type == "FLOAT64"
    return dst_type == "STRING(MAX)"


def _render_property_graph_sql(mapping: SchemaMapping, graph_name: str = "MigratedGraph") -> str:
    validate_identifier(graph_name, graph_name, "graph", "property graph", "graph_name")

    # Track graph-wide label property signatures (for DEF-006 & DEF-035) and node property types.
    node_prop_types: dict[str, tuple[str, str]] = {}
    label_signatures: dict[str, dict[str, str]] = {}

    node_defs: list[str] = []
    for nm in mapping.nodes.values():
        cols = get_node_columns(nm)
        pk_cols = [c.spanner_column for c in cols if c.is_pk]
        node_label_alias = nm.raw_label
        validate_graph_alias(
            node_label_alias,
            kind="LABEL",
            scope=f"node table {nm.spanner_table!r}",
            yaml_hint_section="table_renames",
        )

        prop_exprs: list[str] = []
        sig: dict[str, str] = {}
        for c in cols:
            prop_alias = nm.column_renames.get(c.raw_name, c.raw_name)
            validate_graph_alias(
                prop_alias,
                kind="property",
                scope=f"node table {nm.spanner_table!r}",
                yaml_hint_section=f"nodes.{nm.raw_label}.column_renames",
            )
            prev = node_prop_types.get(prop_alias)
            if prev is not None and prev[0] != c.final_type:
                raise NamingError(
                    f"Property {prop_alias!r} has conflicting types across node tables: "
                    f"{prev[1]} has {prev[0]} vs {nm.spanner_table} has {c.final_type}. "
                    f"Fix by adding a rename under `nodes.{nm.raw_label}.column_renames` or aligning types via `override`."
                )
            node_prop_types[prop_alias] = (c.final_type, nm.spanner_table)
            sig[prop_alias] = c.final_type
            prop_exprs.append(f"{c.spanner_column} AS {spanner_backtick(prop_alias)}")

        if node_label_alias in label_signatures and label_signatures[node_label_alias] != sig:
            raise NamingError(
                f"Graph LABEL {node_label_alias!r} is declared multiple times with different property sets."
            )
        label_signatures[node_label_alias] = sig

        node_defs.append(
            f"  {nm.spanner_table}\n"
            f"    KEY ({', '.join(pk_cols)})\n"
            f"    LABEL {spanner_backtick(node_label_alias)}\n"
            f"    PROPERTIES ({', '.join(prop_exprs)})"
        )

    # Group edge properties by rel_type so polymorphic tables sharing a LABEL
    # declare the exact same set of property names and types (Spanner Graph requirement).
    label_prop_types: dict[str, dict[str, str]] = defaultdict(dict)
    for em in mapping.edges.values():
        src_node = mapping.nodes[em.src_label]
        dst_node = mapping.nodes[em.dst_label]
        cols = get_edge_columns(em, src_node, dst_node)
        for c in cols:
            if c.role in ("src_pk", "dst_pk"):
                continue
            prop_alias = em.column_renames.get(c.raw_name, c.raw_name)
            validate_graph_alias(
                prop_alias,
                kind="property",
                scope=f"edge table {em.spanner_table!r}",
                yaml_hint_section=f"edges.{em.triplet_key}.column_renames",
            )
            prev = label_prop_types[em.rel_type].get(prop_alias)
            if prev is None:
                label_prop_types[em.rel_type][prop_alias] = c.final_type
            elif prev != c.final_type:
                if {prev, c.final_type} == {"INT64", "FLOAT64"}:
                    label_prop_types[em.rel_type][prop_alias] = "FLOAT64"
                elif _can_cast_in_graph_ddl(prev, "STRING(MAX)") and _can_cast_in_graph_ddl(c.final_type, "STRING(MAX)"):
                    label_prop_types[em.rel_type][prop_alias] = "STRING(MAX)"
                else:
                    raise NamingError(
                        f"Edge property {prop_alias!r} on shared LABEL {em.rel_type!r} has incompatible types "
                        f"({prev} vs {c.final_type}) that cannot be CAST in Spanner Graph DDL. "
                        f"Fix by adding a rename under `edges.{em.triplet_key}.column_renames` or aligning types via `override`."
                    )

    edge_defs: list[str] = []
    for em in mapping.edges.values():
        src_node = mapping.nodes[em.src_label]
        dst_node = mapping.nodes[em.dst_label]
        cols = get_edge_columns(em, src_node, dst_node)
        pk_cols = [c.spanner_column for c in cols if c.is_pk]
        src_pk_cols = [c.spanner_column for c in cols if c.role == "src_pk"]
        dst_pk_cols = [c.spanner_column for c in cols if c.role == "dst_pk"]
        src_ref_cols = [src_node.properties[pk].spanner_column for pk in src_node.pk_columns]
        dst_ref_cols = [dst_node.properties[pk].spanner_column for pk in dst_node.pk_columns]

        edge_label_alias = em.rel_type
        validate_graph_alias(
            edge_label_alias,
            kind="LABEL",
            scope=f"edge table {em.spanner_table!r}",
            yaml_hint_section="table_renames",
        )

        cols_by_alias = {
            em.column_renames.get(c.raw_name, c.raw_name): c
            for c in cols
            if c.role not in ("src_pk", "dst_pk")
        }
        shared_props = label_prop_types[em.rel_type]
        if edge_label_alias in label_signatures and label_signatures[edge_label_alias] != shared_props:
            raise NamingError(
                f"Relationship type {em.rel_type!r} shares LABEL {edge_label_alias!r} with a node label "
                f"but has different properties. Rename the label or relationship type."
            )
        label_signatures[edge_label_alias] = dict(shared_props)

        if shared_props:
            prop_exprs = []
            for prop_alias in sorted(shared_props):
                target_type = shared_props[prop_alias]
                if prop_alias in cols_by_alias:
                    c = cols_by_alias[prop_alias]
                    if c.final_type == target_type:
                        prop_exprs.append(f"{c.spanner_column} AS {spanner_backtick(prop_alias)}")
                    else:
                        if not _can_cast_in_graph_ddl(c.final_type, target_type):
                            raise NamingError(
                                f"Cannot CAST {c.spanner_column} ({c.final_type}) to {target_type} "
                                f"in edge table {em.spanner_table!r}."
                            )
                        prop_exprs.append(f"CAST({c.spanner_column} AS {target_type}) AS {spanner_backtick(prop_alias)}")
                else:
                    prop_exprs.append(f"CAST(NULL AS {target_type}) AS {spanner_backtick(prop_alias)}")
            props_clause = f"PROPERTIES ({', '.join(prop_exprs)})"
        else:
            props_clause = "NO PROPERTIES"

        edge_defs.append(
            f"  {em.spanner_table}\n"
            f"    KEY ({', '.join(pk_cols)})\n"
            f"    SOURCE KEY ({', '.join(src_pk_cols)}) REFERENCES {em.src_table} ({', '.join(src_ref_cols)})\n"
            f"    DESTINATION KEY ({', '.join(dst_pk_cols)}) REFERENCES {em.dst_table} ({', '.join(dst_ref_cols)})\n"
            f"    LABEL {spanner_backtick(edge_label_alias)}\n"
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

    node_tables = [(nm.spanner_table, get_node_columns(nm)) for nm in mapping.nodes.values()]
    edge_tables = [
        (em.spanner_table, get_edge_columns(em, mapping.nodes[em.src_label], mapping.nodes[em.dst_label]))
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
