"""Configuration and YAML schema mapping models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

from .types import is_legal_pk_type, is_valid_spanner_type


class ConfigError(ValueError):
    """Raised when schema_mapping.yaml is malformed, empty, or has invalid fields/types."""


def _construct_dc(dc_cls: type[Any], raw: Any, context: str) -> Any:
    if not isinstance(raw, dict):
        raise ConfigError(f"Expected mapping for {context}, got {type(raw).__name__}")
    valid_fields = {f.name for f in fields(dc_cls)}
    unknown = sorted(set(raw.keys()) - valid_fields)
    if unknown:
        raise ConfigError(f"Unknown key(s) in {context}: {', '.join(unknown)}")
    try:
        return dc_cls(**raw)
    except TypeError as exc:
        raise ConfigError(f"Invalid fields in {context}: {exc}") from exc


@dataclass
class PropertyMapping:
    """Mapping and type-inference metadata for a single node or edge property."""

    raw_name: str
    spanner_column: str
    observed: dict[str, int] = field(default_factory=dict)
    null_count: int = 0
    resolved: str = "STRING(MAX)"
    override: str | None = None
    is_conflict: bool = False

    @property
    def effective_type(self) -> str:
        return self.override if self.override else self.resolved


def resolve_effective_type(
    pm: PropertyMapping,
    property_type_overrides: dict[str, str] | None = None,
    *,
    prop_alias: str | None = None,
) -> str:
    """Resolve effective Spanner type with precedence: per-table override > global property_type_overrides > resolved."""
    if pm.override:
        return pm.override
    if property_type_overrides:
        lowered = {k.lower(): v for k, v in property_type_overrides.items()}
        if prop_alias is not None:
            hit = lowered.get(prop_alias.lower())
            if hit:
                return hit
        hit = lowered.get(pm.raw_name.lower())
        if hit:
            return hit
    return pm.resolved


@dataclass
class NodeTableMapping:
    """Mapping for one canonical Neo4j label -> Spanner node table."""

    raw_label: str
    spanner_table: str
    pk_columns: list[str]
    pk_source: str  # yaml_override | node_key | uniqueness_constraint | neo4j_id_fallback
    is_synthetic_pk: bool = False
    monotonic_pk_warning: bool = False
    row_count: int = 0
    has_secondary_labels: bool = False
    secondary_labels_column: str | None = None
    label_sets: list[list[str]] = field(default_factory=list)
    excluded_labels: list[str] = field(default_factory=list)
    properties: dict[str, PropertyMapping] = field(default_factory=dict)
    column_renames: dict[str, str] = field(default_factory=dict)


@dataclass
class EdgeTripletMapping:
    """Mapping for one (src_canonical, rel_type, dst_canonical) -> Spanner edge table."""

    triplet_key: str
    src_label: str
    rel_type: str
    dst_label: str
    spanner_table: str
    src_table: str
    dst_table: str
    has_parallel_edges: bool = False
    edge_id_column: str | None = None
    row_count: int = 0
    properties: dict[str, PropertyMapping] = field(default_factory=dict)
    column_renames: dict[str, str] = field(default_factory=dict)


@dataclass
class SchemaMapping:
    """Top-level schema mapping persisted as schema_mapping.yaml."""

    version: int = 1
    neo4j_version: str = ""
    neo4j_edition: str = ""
    label_priority: list[str] = field(default_factory=list)
    table_renames: dict[str, str] = field(default_factory=dict)
    pk_overrides: dict[str, list[str]] = field(default_factory=dict)
    property_type_overrides: dict[str, str] = field(default_factory=dict)
    nodes: dict[str, NodeTableMapping] = field(default_factory=dict)
    edges: dict[str, EdgeTripletMapping] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SchemaMapping:
        if not isinstance(data, dict):
            raise ConfigError(f"Top-level schema mapping must be a YAML mapping, got {type(data).__name__}")
        valid_top = {f.name for f in fields(cls)}
        unknown_top = sorted(set(data.keys()) - valid_top)
        if unknown_top:
            raise ConfigError(f"Unknown top-level key(s) in schema_mapping.yaml: {', '.join(unknown_top)}")

        nodes: dict[str, NodeTableMapping] = {}
        raw_nodes = data.get("nodes") or {}
        if not isinstance(raw_nodes, dict):
            raise ConfigError("`nodes` in schema_mapping.yaml must be a mapping")
        for k, v in raw_nodes.items():
            if not isinstance(v, dict):
                raise ConfigError(f"Expected mapping for nodes.{k}, got {type(v).__name__}")
            raw_props = v.get("properties") or {}
            if not isinstance(raw_props, dict):
                raise ConfigError(f"`nodes.{k}.properties` must be a mapping")
            props = {
                pk: _construct_dc(PropertyMapping, pv, f"nodes.{k}.properties.{pk}")
                for pk, pv in raw_props.items()
            }
            v_copy = dict(v)
            v_copy["properties"] = props
            nodes[k] = _construct_dc(NodeTableMapping, v_copy, f"nodes.{k}")

        edges: dict[str, EdgeTripletMapping] = {}
        raw_edges = data.get("edges") or {}
        if not isinstance(raw_edges, dict):
            raise ConfigError("`edges` in schema_mapping.yaml must be a mapping")
        for k, v in raw_edges.items():
            if not isinstance(v, dict):
                raise ConfigError(f"Expected mapping for edges.{k}, got {type(v).__name__}")
            raw_props = v.get("properties") or {}
            if not isinstance(raw_props, dict):
                raise ConfigError(f"`edges.{k}.properties` must be a mapping")
            props = {
                pk: _construct_dc(PropertyMapping, pv, f"edges.{k}.properties.{pk}")
                for pk, pv in raw_props.items()
            }
            v_copy = dict(v)
            v_copy["properties"] = props
            edges[k] = _construct_dc(EdgeTripletMapping, v_copy, f"edges.{k}")

        raw_prop_overrides = data.get("property_type_overrides") or {}
        if not isinstance(raw_prop_overrides, dict):
            raise ConfigError("`property_type_overrides` in schema_mapping.yaml must be a mapping")

        return cls(
            version=int(data.get("version", 1)),
            neo4j_version=str(data.get("neo4j_version", "")),
            neo4j_edition=str(data.get("neo4j_edition", "")),
            label_priority=list(data.get("label_priority") or []),
            table_renames=dict(data.get("table_renames") or {}),
            pk_overrides={
                k: list(v) for k, v in (data.get("pk_overrides") or {}).items()
            },
            property_type_overrides={
                str(k): str(v) for k, v in raw_prop_overrides.items()
            },
            nodes=nodes,
            edges=edges,
        )


def save_mapping(mapping: SchemaMapping, path: str | Path) -> None:
    """Write SchemaMapping to YAML preserving key order."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(mapping.to_dict(), fh, sort_keys=False, allow_unicode=True)


def validate_mapping(mapping: SchemaMapping) -> None:
    """Validate overrides, PK types, and structural invariants on a SchemaMapping."""
    if not mapping.nodes:
        raise ConfigError("Schema mapping defines 0 node tables; nothing to export or generate.")

    seen_global_lower: dict[str, tuple[str, str]] = {}
    for prop_name, sp_type in mapping.property_type_overrides.items():
        if not is_valid_spanner_type(sp_type):
            raise ConfigError(
                f"Invalid Spanner type {sp_type!r} in property_type_overrides.{prop_name}."
            )
        low = prop_name.lower()
        if low in seen_global_lower and seen_global_lower[low][1] != sp_type:
            other_name, other_type = seen_global_lower[low]
            raise ConfigError(
                f"Conflicting case-insensitive entries in property_type_overrides: "
                f"{other_name!r} ({other_type}) vs {prop_name!r} ({sp_type})."
            )
        seen_global_lower[low] = (prop_name, sp_type)

    for label, nm in mapping.nodes.items():
        if not nm.pk_columns:
            raise ConfigError(f"Node table {label!r} has no pk_columns.")
        for prop_name, pm in nm.properties.items():
            alias = nm.column_renames.get(prop_name, prop_name)
            eff = resolve_effective_type(pm, mapping.property_type_overrides, prop_alias=alias)
            if not is_valid_spanner_type(eff):
                raise ConfigError(
                    f"Invalid Spanner type {eff!r} on {label}.{prop_name}."
                )
        for pk_col in nm.pk_columns:
            if pk_col not in nm.properties:
                raise ConfigError(f"Primary key column {pk_col!r} missing from {label}.properties.")
            pk_alias = nm.column_renames.get(pk_col, pk_col)
            pk_type = resolve_effective_type(
                nm.properties[pk_col], mapping.property_type_overrides, prop_alias=pk_alias
            )
            if not is_legal_pk_type(pk_type):
                raise ConfigError(
                    f"Column {label}.{pk_col} has type {pk_type}, which is not legal as a Spanner PRIMARY KEY."
                )

    for key, em in mapping.edges.items():
        if em.src_label not in mapping.nodes:
            raise ConfigError(f"Edge {key!r} references unknown src_label {em.src_label!r}.")
        if em.dst_label not in mapping.nodes:
            raise ConfigError(f"Edge {key!r} references unknown dst_label {em.dst_label!r}.")
        for prop_name, pm in em.properties.items():
            alias = em.column_renames.get(prop_name, prop_name)
            eff = resolve_effective_type(pm, mapping.property_type_overrides, prop_alias=alias)
            if not is_valid_spanner_type(eff):
                raise ConfigError(
                    f"Invalid Spanner type {eff!r} on {key}.{prop_name}."
                )


def load_mapping(path: str | Path, *, validate: bool = True) -> SchemaMapping:
    """Load and optionally validate SchemaMapping from a YAML file."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        try:
            data = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ConfigError(f"Malformed YAML in {p}: {exc}") from exc
    if not data:
        if not validate:
            return SchemaMapping()
        raise ConfigError(f"Schema mapping file {p} is empty.")
    mapping = SchemaMapping.from_dict(data)
    if validate:
        validate_mapping(mapping)
    return mapping
