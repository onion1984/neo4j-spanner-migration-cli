"""Neo4j 4.4 LTS vs 5.x version detection, constraint parsing, and Cypher helpers."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_ID_DEPRECATION_LOGGED = False


@dataclass(frozen=True)
class Neo4jCompat:
    """Version-specific compatibility metadata for a connected Neo4j server."""

    version_str: str
    major: int
    minor: int
    patch: int
    edition: str

    @property
    def is_v4(self) -> bool:
        return self.major == 4

    @property
    def is_v5(self) -> bool:
        return self.major >= 5


@dataclass(frozen=True)
class ConstraintInfo:
    """Normalized representation of a Neo4j uniqueness or node-key constraint."""

    name: str
    constraint_type: str  # "NODE_KEY" or "UNIQUENESS"
    labels: tuple[str, ...]
    properties: tuple[str, ...]


def parse_version_tuple(version_str: str) -> tuple[int, int, int]:
    """Parse a Neo4j version string (e.g., '5.23.0', '4.4.35-aura') into (major, minor, patch)."""
    match = re.match(r"^\s*(\d+)\.(\d+)(?:\.(\d+))?", version_str)
    if not match:
        raise ValueError(f"Unrecognized Neo4j version string: {version_str!r}")
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3) or 0)
    return major, minor, patch


def detect_neo4j_compat(driver: Any, database: str) -> Neo4jCompat:
    """Probe the Neo4j server version and edition via dbms.components()."""
    with driver.session(database=database) as session:
        record = session.run(
            "CALL dbms.components() YIELD name, versions, edition "
            "WHERE name = 'Neo4j Kernel' RETURN versions[0] AS version, edition"
        ).single()
        if record is None:
            raise RuntimeError("Failed to detect Neo4j version from dbms.components()")
        version_str = str(record["version"])
        edition = str(record["edition"])
        major, minor, patch = parse_version_tuple(version_str)
        if major not in (4, 5):
            logger.warning("Untested Neo4j major version %s; proceeding with 5.x dialect", version_str)
        return Neo4jCompat(
            version_str=version_str,
            major=major,
            minor=minor,
            patch=patch,
            edition=edition,
        )


def parse_constraint_records(records: list[dict[str, Any]]) -> list[ConstraintInfo]:
    """Normalize SHOW CONSTRAINTS rows across Neo4j 4.4 and 5.x.

    Ignores existence and relationship constraints for primary key purposes.
    """
    results: list[ConstraintInfo] = []
    for row in records:
        raw_type = str(row.get("type") or "").upper()
        entity_type = str(row.get("entityType") or "").upper()
        labels = tuple(row.get("labelsOrTypes") or ())
        props = tuple(row.get("properties") or ())
        name = str(row.get("name") or "")

        if entity_type and entity_type != "NODE":
            continue

        if raw_type in ("NODE_KEY",):
            norm_type = "NODE_KEY"
        elif raw_type in ("UNIQUENESS", "NODE_PROPERTY_UNIQUENESS"):
            norm_type = "UNIQUENESS"
        else:
            # Ignore existence, relationship uniqueness, type constraints, etc.
            continue

        if not labels or not props:
            continue

        results.append(
            ConstraintInfo(
                name=name,
                constraint_type=norm_type,
                labels=labels,
                properties=props,
            )
        )
    return results


def fetch_node_constraints(driver: Any, database: str) -> list[ConstraintInfo]:
    """Query SHOW CONSTRAINTS and return normalized node PK-eligible constraints."""
    with driver.session(database=database) as session:
        records = [dict(r) for r in session.run("SHOW CONSTRAINTS")]
    return parse_constraint_records(records)


def cypher_ident(name: str) -> str:
    """Backtick-quote a Neo4j label, relationship type, or property name safely."""
    escaped = name.replace("`", "``")
    return f"`{escaped}`"


def id_expr(alias: str) -> str:
    """Return the Cypher internal ID expression compatible with both Neo4j 4.4 and 5.x."""
    global _ID_DEPRECATION_LOGGED
    if not _ID_DEPRECATION_LOGGED:
        logger.debug("Using id() for Neo4j 4.4/5.x cross-version internal ID compatibility.")
        logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
        _ID_DEPRECATION_LOGGED = True
    return f"id({alias})"


def label_match_clause(alias: str, canonical_label: str, excluded_labels: list[str]) -> str:
    """Build a Cypher MATCH + optional WHERE NOT clause for a canonical node table."""
    match_part = f"({alias}:{cypher_ident(canonical_label)})"
    if not excluded_labels:
        return match_part
    return match_part


def label_where_predicate(alias: str, excluded_labels: list[str]) -> str:
    """Return a WHERE predicate excluding higher-priority/conflicting labels (or empty string)."""
    if not excluded_labels:
        return ""
    checks = " OR ".join(f"{alias}:{cypher_ident(lbl)}" for lbl in excluded_labels)
    return f"NOT ({checks})"
