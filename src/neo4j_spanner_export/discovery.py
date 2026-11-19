"""Full-scan Neo4j discovery: canonical labels, PKs, triplets, type inference, and report."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

from .compat import (
    ConstraintInfo,
    cypher_ident,
    detect_neo4j_compat,
    fetch_node_constraints,
    id_expr,
    label_where_predicate,
)
from .config import (
    EdgeTripletMapping,
    NodeTableMapping,
    PropertyMapping,
    SchemaMapping,
    load_mapping,
    save_mapping,
    validate_mapping,
)
from .naming import resolve_identifiers
from .types import MAX_SAFE_FLOAT64_INT, classify_value, is_legal_pk_type, widen_types

MAX_SPANNER_COLUMNS = 1024

logger = logging.getLogger(__name__)


class DiscoveryError(RuntimeError):
    """Raised when discovery encounters unresolvable ambiguity or invalid data."""


@dataclass
class _LabelSetInfo:
    labels: tuple[str, ...]
    count: int
    canonical: str


def _resolve_canonical_labels(
    label_sets: list[tuple[tuple[str, ...], int]],
    constraints: list[ConstraintInfo],
    label_priority: list[str],
) -> list[_LabelSetInfo]:
    """Resolve each distinct node label set to exactly one canonical label."""
    constrained_labels: set[str] = set()
    for c in constraints:
        if len(c.labels) == 1:
            constrained_labels.add(c.labels[0])

    resolved: list[_LabelSetInfo] = []
    conflicts: list[tuple[tuple[str, ...], int, str]] = []

    for lbls, cnt in label_sets:
        if not lbls:
            raise DiscoveryError(
                f"Found {cnt} node(s) with no labels. All nodes must have at least one label."
            )
        chosen: str | None = None
        # 1. YAML label_priority
        for prio in label_priority:
            if prio in lbls:
                chosen = prio
                break

        # 2. Constraint-bearing label
        if chosen is None:
            matching_constrained = [l for l in lbls if l in constrained_labels]
            if len(matching_constrained) == 1:
                chosen = matching_constrained[0]
            elif len(matching_constrained) > 1:
                conflicts.append(
                    (lbls, cnt, f"multiple constrained labels: {matching_constrained}")
                )
                continue

        # 3. Single label
        if chosen is None:
            if len(lbls) == 1:
                chosen = lbls[0]
            else:
                conflicts.append((lbls, cnt, "multi-label with no constraint or label_priority"))
                continue

        resolved.append(_LabelSetInfo(labels=lbls, count=cnt, canonical=chosen))

    if conflicts:
        lines = [
            "Ambiguous multi-label nodes detected. Add `label_priority` to schema_mapping.yaml "
            "or pass `--label-priority`:"
        ]
        for lbls, cnt, reason in conflicts:
            lines.append(f"  - labels={list(lbls)} (count={cnt}): {reason}")
        raise DiscoveryError("\n".join(lines))

    return resolved


def _check_uniqueness_non_null(
    driver: Any,
    database: str,
    canonical_label: str,
    excluded_labels: list[str],
    prop: str,
) -> bool:
    """Return True if no node in the canonical table has NULL for `prop`."""
    where_parts = [f"n.{cypher_ident(prop)} IS NULL"]
    excl = label_where_predicate("n", excluded_labels)
    if excl:
        where_parts.append(excl)
    query = (
        f"MATCH (n:{cypher_ident(canonical_label)}) "
        f"WHERE {' AND '.join(where_parts)} "
        f"RETURN count(n) > 0 AS has_null LIMIT 1"
    )
    with driver.session(database=database) as session:
        rec = session.run(query).single()
        return not bool(rec and rec["has_null"])


def _resolve_node_pk(
    driver: Any,
    database: str,
    canonical_label: str,
    excluded_labels: list[str],
    constraints: list[ConstraintInfo],
    pk_overrides: dict[str, list[str]],
) -> tuple[list[str], str, bool]:
    """Resolve primary key columns for a canonical node table.

    Returns (pk_columns, pk_source, is_synthetic_pk).
    """
    if canonical_label in pk_overrides and pk_overrides[canonical_label]:
        return list(pk_overrides[canonical_label]), "yaml_override", False

    node_keys = [
        c for c in constraints
        if c.constraint_type == "NODE_KEY" and c.labels == (canonical_label,)
    ]
    if node_keys:
        # Prefer single-property NODE_KEY or shortest composite
        best = sorted(node_keys, key=lambda c: (len(c.properties), c.properties))[0]
        return list(best.properties), "node_key", False

    uniques = [
        c for c in constraints
        if c.constraint_type == "UNIQUENESS" and c.labels == (canonical_label,)
    ]
    for u in sorted(uniques, key=lambda c: (len(c.properties), c.properties)):
        if all(
            _check_uniqueness_non_null(driver, database, canonical_label, excluded_labels, p)
            for p in u.properties
        ):
            return list(u.properties), "uniqueness_constraint", False
        logger.warning(
            "Uniqueness constraint %s on %s(%s) contains NULLs; cannot use as Spanner PK.",
            u.name,
            canonical_label,
            ", ".join(u.properties),
        )

    logger.warning(
        "No non-null uniqueness/NODE_KEY constraint on %s; falling back to bit-reversed _neo4j_id.",
        canonical_label,
    )
    return ["_neo4j_id"], "neo4j_id_fallback", True


def _check_pk_uniqueness(
    driver: Any,
    database: str,
    canonical_label: str,
    excluded_labels: list[str],
    pk_cols: list[str],
) -> None:
    """Raise DiscoveryError if pk_cols has duplicate values in Neo4j."""
    excl = label_where_predicate("n", excluded_labels)
    where_sql = f"WHERE {excl} " if excl else ""
    key_expr = ", ".join(f"n.{cypher_ident(p)} AS _k{i}" for i, p in enumerate(pk_cols))
    query = (
        f"MATCH (n:{cypher_ident(canonical_label)}) {where_sql}"
        f"WITH {key_expr}, count(*) AS cnt WHERE cnt > 1 "
        f"RETURN cnt LIMIT 1"
    )
    with driver.session(database=database) as session:
        rec = session.run(query).single()
        if rec is not None:
            raise DiscoveryError(
                f"Configured pk_override {pk_cols} on {canonical_label!r} is not unique "
                f"(found duplicate key with count={rec['cnt']})."
            )


def _looks_monotonic(values: list[Any]) -> bool:
    """Heuristic: return True if >= 10 numeric/temporal values are strictly non-decreasing
    or form a dense sequential integer series regardless of scan order.
    """
    if len(values) < 10:
        return False
    try:
        non_dec = sum(1 for a, b in zip(values, values[1:]) if b >= a)
        if non_dec >= len(values) - 1:
            return True
        if all(isinstance(v, int) and not isinstance(v, bool) for v in values):
            s = sorted(set(values))
            if len(s) >= 10 and (s[-1] - s[0]) <= 2 * len(s):
                return True
        return False
    except TypeError:
        return False


def discover_schema(
    driver: Any,
    database: str,
    output_mapping_path: Path,
    input_mapping_path: Path | None = None,
    label_priority: list[str] | None = None,
    sample_size: int | None = None,
    report_path: Path | None = None,
) -> SchemaMapping:
    """Run full (or sampled) discovery on Neo4j and write schema_mapping.yaml + report."""
    existing = (
        load_mapping(input_mapping_path, validate=False)
        if input_mapping_path and input_mapping_path.exists()
        else None
    )
    merged_priority = list(label_priority or (existing.label_priority if existing else []))
    table_renames = dict(existing.table_renames if existing else {})
    pk_overrides = dict(existing.pk_overrides if existing else {})

    compat = detect_neo4j_compat(driver, database)
    constraints = fetch_node_constraints(driver, database)

    # 1. Discover label sets
    with driver.session(database=database) as session:
        raw_label_sets = [
            (tuple(sorted(r["lbls"])), int(r["cnt"]))
            for r in session.run("MATCH (n) RETURN labels(n) AS lbls, count(*) AS cnt")
        ]

    if not raw_label_sets:
        raise DiscoveryError("Neo4j database is empty (0 nodes); cannot generate a Spanner schema.")

    resolved_sets = _resolve_canonical_labels(raw_label_sets, constraints, merged_priority)

    # Group label sets by canonical label
    by_canonical: dict[str, list[_LabelSetInfo]] = defaultdict(list)
    for info in resolved_sets:
        by_canonical[info.canonical].append(info)

    # Map frozenset(labels) -> canonical for quick lookup during edge discovery
    labelset_to_canonical: dict[frozenset[str], str] = {
        frozenset(info.labels): info.canonical for info in resolved_sets
    }

    # Compute excluded_labels per canonical label
    excluded_by_canonical: dict[str, list[str]] = {}
    for canonical in by_canonical:
        excl: set[str] = set()
        for info in resolved_sets:
            if canonical in info.labels and info.canonical != canonical:
                excl.add(info.canonical)
        excluded_by_canonical[canonical] = sorted(excl)

    # 2. Scan each canonical node table
    node_mappings: dict[str, NodeTableMapping] = {}
    for canonical, infos in sorted(by_canonical.items()):
        excluded = excluded_by_canonical[canonical]
        pk_cols, pk_source, is_synthetic = _resolve_node_pk(
            driver, database, canonical, excluded, constraints, pk_overrides
        )

        # Scan properties
        where_clause = label_where_predicate("n", excluded)
        where_sql = f"WHERE {where_clause} " if where_clause else ""
        limit_sql = f"LIMIT {int(sample_size)}" if sample_size else ""
        query = (
            f"MATCH (n:{cypher_ident(canonical)}) {where_sql}"
            f"RETURN properties(n) AS props, {id_expr('n')} AS nid {limit_sql}"
        )

        observed_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        null_counts: dict[str, int] = defaultdict(int)
        large_int_props: set[str] = set()
        all_prop_names: set[str] = set()
        row_count = 0
        leading_pk_samples: list[Any] = []
        leading_pk_name = pk_cols[0]

        with driver.session(database=database) as session:
            for record in session.run(query):
                row_count += 1
                props: dict[str, Any] = record["props"] or {}
                for k in props:
                    all_prop_names.add(k)
                for k, v in props.items():
                    t = classify_value(v)
                    if t == "NULL":
                        null_counts[k] += 1
                    else:
                        observed_counts[k][t] += 1
                        if isinstance(v, int) and not isinstance(v, bool) and abs(v) > MAX_SAFE_FLOAT64_INT:
                            large_int_props.add(k)
                if not is_synthetic and len(leading_pk_samples) < 500:
                    pk_val = props.get(leading_pk_name)
                    if pk_val is not None:
                        leading_pk_samples.append(pk_val)

        # Count implicit nulls (nodes that lack a property present on other nodes)
        for k in all_prop_names:
            present_non_null = sum(observed_counts[k].values())
            explicit_nulls = null_counts[k]
            missing = max(0, row_count - present_non_null - explicit_nulls)
            null_counts[k] = explicit_nulls + missing

        # Ensure PK columns exist in properties (for non-synthetic PKs)
        if not is_synthetic:
            for pcol in pk_cols:
                if pcol not in all_prop_names:
                    raise DiscoveryError(
                        f"Configured PK column {pcol!r} on {canonical} was not found on any node."
                    )
                if null_counts.get(pcol, 0) > 0:
                    raise DiscoveryError(
                        f"PK column {pcol!r} on {canonical} has {null_counts[pcol]} NULL value(s)."
                    )

        has_secondary = any(len(info.labels) > 1 for info in infos)

        existing_node = existing.nodes.get(canonical) if existing else None
        col_renames = dict(existing_node.column_renames if existing_node else {})
        existing_props = existing_node.properties if existing_node else {}

        # Resolve column identifiers for this node table
        raw_cols: list[str] = []
        if is_synthetic:
            raw_cols.append("_neo4j_id")
        if has_secondary:
            raw_cols.append("secondary_labels")
        for p in sorted(all_prop_names):
            raw_cols.append(p)

        if len(raw_cols) > MAX_SPANNER_COLUMNS:
            raise DiscoveryError(
                f"Node table {canonical!r} has {len(raw_cols)} columns, exceeding Spanner's "
                f"limit of {MAX_SPANNER_COLUMNS} columns per table."
            )

        col_id_map = resolve_identifiers(
            [(c, col_renames.get(c)) for c in raw_cols],
            kind="column",
            scope=f"node table {canonical!r}",
            yaml_hint_section=f"nodes.{canonical}.column_renames",
        )

        prop_mappings: dict[str, PropertyMapping] = {}
        if is_synthetic:
            prop_mappings["_neo4j_id"] = PropertyMapping(
                raw_name="_neo4j_id",
                spanner_column=col_id_map["_neo4j_id"],
                observed={"INT64": row_count},
                null_count=0,
                resolved="INT64",
                override=(existing_props["_neo4j_id"].override if "_neo4j_id" in existing_props else None),
                is_conflict=False,
            )

        if has_secondary:
            prop_mappings["secondary_labels"] = PropertyMapping(
                raw_name="secondary_labels",
                spanner_column=col_id_map["secondary_labels"],
                observed={"LIST<STRING>": row_count},
                null_count=0,
                resolved="ARRAY<STRING(MAX)>",
                override=(
                    existing_props["secondary_labels"].override
                    if "secondary_labels" in existing_props
                    else None
                ),
                is_conflict=False,
            )

        for p in sorted(all_prop_names):
            obs = {k: observed_counts[p][k] for k in sorted(observed_counts[p])}
            resolved_type, is_conflict = widen_types(obs, has_large_int=(p in large_int_props))
            prev_override = existing_props[p].override if p in existing_props else None
            prop_mappings[p] = PropertyMapping(
                raw_name=p,
                spanner_column=col_id_map[p],
                observed=obs,
                null_count=null_counts[p],
                resolved=resolved_type,
                override=prev_override,
                is_conflict=is_conflict,
            )

        if not is_synthetic:
            for pcol in pk_cols:
                eff = prop_mappings[pcol].effective_type
                if not is_legal_pk_type(eff):
                    raise DiscoveryError(
                        f"PK column {pcol!r} on {canonical!r} has type {eff}, which is not legal as a Spanner PRIMARY KEY."
                    )
                if prop_mappings[pcol].is_conflict:
                    raise DiscoveryError(
                        f"PK column {pcol!r} on {canonical!r} has mixed types ({sorted(prop_mappings[pcol].observed.keys())}); "
                        f"widening to {eff} can collapse distinct Neo4j keys into duplicate Spanner PKs. "
                        f"Normalize types in Neo4j or use _neo4j_id."
                    )
            if pk_source == "yaml_override":
                _check_pk_uniqueness(driver, database, canonical, excluded, pk_cols)

        monotonic_warn = False
        if not is_synthetic:
            lead_type = prop_mappings[leading_pk_name].effective_type
            if lead_type in ("INT64", "TIMESTAMP") and _looks_monotonic(leading_pk_samples):
                monotonic_warn = True

        node_mappings[canonical] = NodeTableMapping(
            raw_label=canonical,
            spanner_table=canonical,  # resolved below in DB-wide scope
            pk_columns=pk_cols,
            pk_source=pk_source,
            is_synthetic_pk=is_synthetic,
            monotonic_pk_warning=monotonic_warn,
            row_count=row_count,
            has_secondary_labels=has_secondary,
            secondary_labels_column=(col_id_map["secondary_labels"] if has_secondary else None),
            label_sets=[list(info.labels) for info in infos],
            excluded_labels=excluded,
            properties=prop_mappings,
            column_renames=col_renames,
        )

    # 3. Discover edge triplets
    with driver.session(database=database) as session:
        raw_triplets = [
            (tuple(sorted(r["src"])), str(r["rel_type"]), tuple(sorted(r["dst"])), int(r["cnt"]))
            for r in session.run(
                "MATCH (a)-[r]->(b) "
                "RETURN labels(a) AS src, type(r) AS rel_type, labels(b) AS dst, count(*) AS cnt"
            )
        ]

    grouped_triplets: dict[tuple[str, str, str], int] = defaultdict(int)
    for src_lbls, rel_type, dst_lbls, cnt in raw_triplets:
        src_can = labelset_to_canonical[frozenset(src_lbls)]
        dst_can = labelset_to_canonical[frozenset(dst_lbls)]
        grouped_triplets[(src_can, rel_type, dst_can)] += cnt

    edge_mappings: dict[str, EdgeTripletMapping] = {}
    for src_can, rel_type, dst_can in sorted(grouped_triplets):
        triplet_key = f"{src_can}__{rel_type}__{dst_can}"
        src_node = node_mappings[src_can]
        dst_node = node_mappings[dst_can]

        src_excl = label_where_predicate("a", src_node.excluded_labels)
        dst_excl = label_where_predicate("b", dst_node.excluded_labels)
        where_parts = [p for p in (src_excl, dst_excl) if p]
        where_sql = f"WHERE {' AND '.join(where_parts)} " if where_parts else ""

        # Parallel edge check (Q3)
        parallel_query = (
            f"MATCH (a:{cypher_ident(src_can)})-[r:{cypher_ident(rel_type)}]->(b:{cypher_ident(dst_can)}) "
            f"{where_sql}"
            f"WITH {id_expr('a')} AS s, {id_expr('b')} AS d, count(r) AS c "
            f"WHERE c > 1 RETURN count(*) > 0 AS has_parallel LIMIT 1"
        )
        with driver.session(database=database) as session:
            prec = session.run(parallel_query).single()
            has_parallel = bool(prec and prec["has_parallel"])

        # Stream edge properties
        limit_sql = f"LIMIT {int(sample_size)}" if sample_size else ""
        edge_query = (
            f"MATCH (a:{cypher_ident(src_can)})-[r:{cypher_ident(rel_type)}]->(b:{cypher_ident(dst_can)}) "
            f"{where_sql}"
            f"RETURN properties(r) AS props {limit_sql}"
        )
        observed_counts = defaultdict(lambda: defaultdict(int))
        null_counts = defaultdict(int)
        large_int_props = set()
        all_prop_names = set()
        row_count = 0

        with driver.session(database=database) as session:
            for record in session.run(edge_query):
                row_count += 1
                props = record["props"] or {}
                for k in props:
                    all_prop_names.add(k)
                for k, v in props.items():
                    t = classify_value(v)
                    if t == "NULL":
                        null_counts[k] += 1
                    else:
                        observed_counts[k][t] += 1
                        if isinstance(v, int) and not isinstance(v, bool) and abs(v) > MAX_SAFE_FLOAT64_INT:
                            large_int_props.add(k)

        for k in all_prop_names:
            present_non_null = sum(observed_counts[k].values())
            explicit_nulls = null_counts[k]
            null_counts[k] = explicit_nulls + max(0, row_count - present_non_null - explicit_nulls)

        existing_edge = existing.edges.get(triplet_key) if existing else None
        col_renames = dict(existing_edge.column_renames if existing_edge else {})
        existing_props = existing_edge.properties if existing_edge else {}

        # Edge table columns: src PKs (inherited exact names), dst PKs (dst_<col>), optional edge_id, then edge props
        fixed_cols_lower: set[str] = set()
        for pk_raw in src_node.pk_columns:
            fixed_cols_lower.add(src_node.properties[pk_raw].spanner_column.lower())
        for pk_raw in dst_node.pk_columns:
            fixed_cols_lower.add(f"dst_{dst_node.properties[pk_raw].spanner_column}".lower())
        if has_parallel:
            fixed_cols_lower.add("edge_id")

        total_edge_cols = len(fixed_cols_lower) + len(all_prop_names)
        if total_edge_cols > MAX_SPANNER_COLUMNS:
            raise DiscoveryError(
                f"Edge table {triplet_key!r} has {total_edge_cols} columns, exceeding Spanner's "
                f"limit of {MAX_SPANNER_COLUMNS} columns per table."
            )

        col_id_map = resolve_identifiers(
            [(p, col_renames.get(p)) for p in sorted(all_prop_names)],
            kind="column",
            scope=f"edge table {triplet_key!r}",
            yaml_hint_section=f"edges.{triplet_key}.column_renames",
        )
        for raw_p, sp_col in col_id_map.items():
            if sp_col.lower() in fixed_cols_lower:
                raise DiscoveryError(
                    f"Edge property {raw_p!r} on {triplet_key!r} collides with key column {sp_col!r}. "
                    f"Add a rename under `edges.{triplet_key}.column_renames` in schema_mapping.yaml."
                )

        prop_mappings = {}
        for p in sorted(all_prop_names):
            obs = {k: observed_counts[p][k] for k in sorted(observed_counts[p])}
            resolved_type, is_conflict = widen_types(obs, has_large_int=(p in large_int_props))
            prev_override = existing_props[p].override if p in existing_props else None
            prop_mappings[p] = PropertyMapping(
                raw_name=p,
                spanner_column=col_id_map[p],
                observed=obs,
                null_count=null_counts[p],
                resolved=resolved_type,
                override=prev_override,
                is_conflict=is_conflict,
            )

        edge_mappings[triplet_key] = EdgeTripletMapping(
            triplet_key=triplet_key,
            src_label=src_can,
            rel_type=rel_type,
            dst_label=dst_can,
            spanner_table=triplet_key,  # resolved below
            src_table=src_can,          # resolved below
            dst_table=dst_can,          # resolved below
            has_parallel_edges=has_parallel,
            edge_id_column="edge_id" if has_parallel else None,
            row_count=row_count,
            properties=prop_mappings,
            column_renames=col_renames,
        )

    # 4. Resolve all table names in one DB-wide scope
    table_items: list[tuple[str, str | None]] = []
    for k in node_mappings:
        table_items.append((k, table_renames.get(k)))
    for k in edge_mappings:
        table_items.append((k, table_renames.get(k)))

    resolved_tables = resolve_identifiers(
        table_items,
        kind="table",
        scope="Spanner database",
        yaml_hint_section="table_renames",
    )

    for k, nm in node_mappings.items():
        nm.spanner_table = resolved_tables[k]
    for k, em in edge_mappings.items():
        em.spanner_table = resolved_tables[k]
        em.src_table = resolved_tables[em.src_label]
        em.dst_table = resolved_tables[em.dst_label]

    mapping = SchemaMapping(
        version=1,
        neo4j_version=compat.version_str,
        neo4j_edition=compat.edition,
        label_priority=merged_priority,
        table_renames=table_renames,
        pk_overrides=pk_overrides,
        nodes=node_mappings,
        edges=edge_mappings,
    )
    validate_mapping(mapping)
    save_mapping(mapping, output_mapping_path)

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_discovery_report(mapping), encoding="utf-8")

    return mapping


def render_discovery_report(mapping: SchemaMapping) -> str:
    """Render a human-readable Markdown discovery report."""
    lines: list[str] = [
        "# Neo4j Discovery Report",
        "",
        f"- **Neo4j Version:** `{mapping.neo4j_version}` ({mapping.neo4j_edition})",
        f"- **Node Tables:** {len(mapping.nodes)}",
        f"- **Edge Triplet Tables:** {len(mapping.edges)}",
        "",
        "## Node Tables",
        "",
        "| Canonical Label | Spanner Table | Rows | PK Columns | PK Source | Label Sets | Warnings |",
        "| :--- | :--- | ---: | :--- | :--- | :--- | :--- |",
    ]
    for nm in mapping.nodes.values():
        warns: list[str] = []
        if nm.is_synthetic_pk:
            warns.append("synthetic `_neo4j_id` (bit-reversed)")
        if nm.monotonic_pk_warning:
            warns.append("monotonic leading PK (hotspot risk)")
        conflicts = [p.raw_name for p in nm.properties.values() if p.is_conflict]
        if conflicts:
            warns.append(f"type conflicts: {', '.join(conflicts)}")
        lbl_sets_str = ", ".join(str(ls) for ls in nm.label_sets)
        lines.append(
            f"| `{nm.raw_label}` | `{nm.spanner_table}` | {nm.row_count} | "
            f"`{', '.join(nm.pk_columns)}` | `{nm.pk_source}` | `{lbl_sets_str}` | "
            f"{'; '.join(warns) or '—'} |"
        )

    lines.extend(
        [
            "",
            "## Edge Triplet Tables",
            "",
            "| Triplet | Spanner Table | Rows | Parallel Edges (`edge_id`) | Type Conflicts |",
            "| :--- | :--- | ---: | :--- | :--- |",
        ]
    )
    for em in mapping.edges.values():
        conflicts = [p.raw_name for p in em.properties.values() if p.is_conflict]
        lines.append(
            f"| `({em.src_label})-[:{em.rel_type}]->({em.dst_label})` | `{em.spanner_table}` | "
            f"{em.row_count} | {'Yes' if em.has_parallel_edges else 'No'} | "
            f"{', '.join(conflicts) or '—'} |"
        )

    multi_label_tables = [nm.raw_label for nm in mapping.nodes.values() if nm.has_secondary_labels]
    if multi_label_tables:
        lines.extend(
            [
                "",
                "## Secondary Labels (GQL Querying Note)",
                "",
                f"Node tables with multi-label rows ({', '.join(f'`{t}`' for t in multi_label_tables)}) "
                "store non-canonical labels in `secondary_labels` (`ARRAY<STRING(MAX)>`).",
                "In Spanner GQL, filter by secondary label using `WHERE 'Label' IN UNNEST(n.secondary_labels)` "
                "instead of `MATCH (n:Label)`.",
            ]
        )

    return "\n".join(lines) + "\n"
