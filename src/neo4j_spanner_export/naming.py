"""Identifier sanitization, truncation, collision checks, and reserved keyword validation."""

from __future__ import annotations

import hashlib
import re
from typing import Iterable

MAX_SPANNER_IDENT_LEN = 128

# GoogleSQL & Spanner Graph reserved keywords (uppercase).
GOOGLESQL_RESERVED_KEYWORDS: frozenset[str] = frozenset(
    {
        "ALL",
        "AND",
        "ANY",
        "ARRAY",
        "AS",
        "ASC",
        "ASSERT_ROWS_MODIFIED",
        "AT",
        "BETWEEN",
        "BY",
        "CASE",
        "CAST",
        "COLLATE",
        "CONTAINS",
        "CREATE",
        "CROSS",
        "CUBE",
        "CURRENT",
        "DEFAULT",
        "DEFINE",
        "DESC",
        "DISTINCT",
        "ELSE",
        "END",
        "ENUM",
        "ESCAPE",
        "EXCEPT",
        "EXCLUDE",
        "EXISTS",
        "EXTRACT",
        "FALSE",
        "FETCH",
        "FOLLOWING",
        "FOR",
        "FROM",
        "FULL",
        "GRAPH_TABLE",
        "GROUP",
        "GROUPING",
        "GROUPS",
        "HASH",
        "HAVING",
        "IF",
        "IGNORE",
        "IN",
        "INNER",
        "INTERSECT",
        "INTERVAL",
        "INTO",
        "IS",
        "JOIN",
        "LATERAL",
        "LEFT",
        "LIKE",
        "LIMIT",
        "LOOKUP",
        "MERGE",
        "NATURAL",
        "NEW",
        "NO",
        "NOT",
        "NULL",
        "NULLS",
        "OF",
        "ON",
        "OR",
        "ORDER",
        "OUTER",
        "OVER",
        "PARTITION",
        "PRECEDING",
        "PROTO",
        "RANGE",
        "RECURSIVE",
        "RESPECT",
        "RIGHT",
        "ROLLUP",
        "ROWS",
        "SELECT",
        "SET",
        "SOME",
        "STRUCT",
        "TABLESAMPLE",
        "THEN",
        "TO",
        "TREAT",
        "TRUE",
        "UNBOUNDED",
        "UNION",
        "UNNEST",
        "USING",
        "WHEN",
        "WHERE",
        "WINDOW",
        "WITH",
        "WITHIN",
    }
)

_VALID_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class NamingError(ValueError):
    """Raised when identifier sanitization hits a reserved word or collision."""


def sanitize_identifier(raw: str, max_len: int = MAX_SPANNER_IDENT_LEN) -> str:
    """Sanitize an arbitrary Neo4j identifier to [A-Za-z][A-Za-z0-9_]* within max_len.

    If longer than max_len, truncates to (max_len - 9) chars + '_' + 8-char sha256 hex.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"id_{cleaned}"
    if len(cleaned) > max_len:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
        prefix_len = max_len - 9
        cleaned = f"{cleaned[:prefix_len]}_{digest}"
    return cleaned


def validate_identifier(
    candidate: str,
    raw_name: str,
    kind: str,
    scope: str,
    yaml_hint_section: str,
) -> None:
    """Validate identifier syntax and reserved-keyword constraints."""
    if len(candidate) > MAX_SPANNER_IDENT_LEN or not _VALID_IDENT_RE.match(candidate):
        raise NamingError(
            f"Invalid Spanner {kind} identifier {candidate!r} (from {raw_name!r}) in {scope}. "
            f"Must match [A-Za-z][A-Za-z0-9_]* and be <= {MAX_SPANNER_IDENT_LEN} chars. "
            f"Add a rename under `{yaml_hint_section}` in schema_mapping.yaml."
        )
    if candidate.upper() in GOOGLESQL_RESERVED_KEYWORDS:
        raise NamingError(
            f"Spanner {kind} identifier {candidate!r} (from {raw_name!r}) in {scope} "
            f"is a GoogleSQL reserved keyword. "
            f"Fix by adding `{raw_name}: <new_name>` under `{yaml_hint_section}` in schema_mapping.yaml."
        )


def resolve_identifiers(
    items: Iterable[tuple[str, str | None]],
    kind: str,
    scope: str,
    yaml_hint_section: str,
) -> dict[str, str]:
    """Resolve (raw_name, optional_yaml_rename) pairs to collision-free Spanner identifiers.

    Checks case-insensitive uniqueness within the scope and GoogleSQL reserved keywords.
    """
    mapping: dict[str, str] = {}
    seen_lower: dict[str, str] = {}
    for raw_name, yaml_rename in items:
        candidate = yaml_rename if yaml_rename else sanitize_identifier(raw_name)
        validate_identifier(candidate, raw_name, kind, scope, yaml_hint_section)
        lowered = candidate.lower()
        if lowered in seen_lower:
            other_raw = seen_lower[lowered]
            raise NamingError(
                f"Case-insensitive {kind} identifier collision in {scope}: "
                f"{raw_name!r} and {other_raw!r} both map to {candidate!r}. "
                f"Fix by adding a rename under `{yaml_hint_section}` in schema_mapping.yaml."
            )
        seen_lower[lowered] = raw_name
        mapping[raw_name] = candidate
    return mapping


def derive_prefixed_identifier(
    prefix: str,
    base: str,
    suffix: str = "",
    max_len: int = MAX_SPANNER_IDENT_LEN,
) -> str:
    """Build `<prefix><base><suffix>` within max_len, using a deterministic hash on overflow."""
    full = f"{prefix}{base}{suffix}"
    if len(full) <= max_len:
        return full
    digest = hashlib.sha256(full.encode("utf-8")).hexdigest()[:8]
    keep = max_len - len(prefix) - len(suffix) - 9
    if keep < 1:
        return f"{prefix[: max_len - 9]}_{digest}"
    return f"{prefix}{base[:keep]}_{digest}{suffix}"


_GCS_PREFIX_RE = re.compile(r"^gs://[a-z0-9][a-z0-9._-]*(/[A-Za-z0-9._/@+-]+)*/?$")


def validate_gcs_prefix(gcs_prefix: str) -> None:
    """Validate that gcs_prefix is a safe gs:// URI without shell metacharacters."""
    if not _GCS_PREFIX_RE.match(gcs_prefix):
        raise NamingError(
            f"Invalid --gcs-prefix {gcs_prefix!r}. Must match gs://<bucket>[/<path>] "
            f"using only [A-Za-z0-9._/@+-] characters."
        )


def validate_graph_alias(
    alias: str,
    kind: str,
    scope: str,
    yaml_hint_section: str,
) -> None:
    """Validate that a Spanner Graph LABEL or PROPERTIES alias is accepted by Spanner DDL."""
    if not alias or alias[0].isdigit() or "\\" in alias or "`" in alias:
        raise NamingError(
            f"Spanner Graph {kind} alias {alias!r} in {scope} cannot start with a digit or contain '\\' or '`'. "
            f"Add a rename under `{yaml_hint_section}` in schema_mapping.yaml."
        )


def spanner_backtick(name: str) -> str:
    """Backtick-quote an original Neo4j name for Spanner PROPERTY GRAPH DDL."""
    escaped = name.replace("`", "``")
    return f"`{escaped}`"
