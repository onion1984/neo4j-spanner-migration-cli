"""Neo4j value type classification, widening lattice, and Spanner type mapping."""

from __future__ import annotations

import datetime
from typing import Any

from neo4j.spatial import Point
from neo4j.time import Date as Neo4jDate
from neo4j.time import DateTime as Neo4jDateTime
from neo4j.time import Duration as Neo4jDuration
from neo4j.time import Time as Neo4jTime

SCALAR_LIST_TYPES = {
    "LIST<BOOL>": "BOOL",
    "LIST<INT64>": "INT64",
    "LIST<FLOAT64>": "FLOAT64",
    "LIST<STRING>": "STRING(MAX)",
}

MAX_SAFE_FLOAT64_INT = 2**53

VALID_SPANNER_TYPES: frozenset[str] = frozenset(
    {
        "BOOL",
        "INT64",
        "FLOAT64",
        "STRING(MAX)",
        "BYTES(MAX)",
        "DATE",
        "TIMESTAMP",
        "JSON",
        "ARRAY<BOOL>",
        "ARRAY<INT64>",
        "ARRAY<FLOAT64>",
        "ARRAY<STRING(MAX)>",
    }
)


def is_valid_spanner_type(spanner_type: str) -> bool:
    """Return True if spanner_type is a supported Spanner DDL column type."""
    return spanner_type in VALID_SPANNER_TYPES


def is_legal_pk_type(spanner_type: str) -> bool:
    """Return True if spanner_type is legal as a Spanner PRIMARY KEY column."""
    return is_valid_spanner_type(spanner_type) and spanner_type != "JSON" and not is_array_type(spanner_type)


def _classify_scalar(value: Any) -> str | None:
    """Classify a non-list, non-null Neo4j value."""
    # bool is a subclass of int in Python, so check bool first.
    if isinstance(value, bool):
        return "BOOL"
    if isinstance(value, int):
        return "INT64"
    if isinstance(value, float):
        return "FLOAT64"
    if isinstance(value, str):
        return "STRING"
    if isinstance(value, (bytes, bytearray)):
        return "BYTES"
    if isinstance(value, (Neo4jDateTime, datetime.datetime)):
        return "DATETIME"
    if isinstance(value, (Neo4jDate, datetime.date)):
        return "DATE"
    if isinstance(value, (Neo4jTime, datetime.time)):
        return "TIME"
    if isinstance(value, (Neo4jDuration, datetime.timedelta)):
        return "DURATION"
    if isinstance(value, Point):
        return "POINT"
    if isinstance(value, dict):
        return "MAP"
    return None


def classify_value(value: Any) -> str:
    """Classify a single Neo4j property value into an observed type token.

    Returns 'NULL' for None.
    """
    if value is None:
        return "NULL"
    if type(value).__name__ == "BrokenHydrationObject":
        raise ValueError(f"Unsupported or out-of-range Neo4j temporal/hydration value: {value!r}")
    scalar = _classify_scalar(value)
    if scalar is not None:
        return scalar
    if isinstance(value, list):
        if len(value) == 0:
            return "LIST_EMPTY"
        elem_types: set[str] = set()
        for item in value:
            if item is None or isinstance(item, list):
                return "LIST_MIXED"
            item_t = _classify_scalar(item)
            if item_t not in ("BOOL", "INT64", "FLOAT64", "STRING"):
                return "LIST_MIXED"
            elem_types.add(item_t)
        if len(elem_types) == 1:
            only = next(iter(elem_types))
            return f"LIST<{only}>"
        if elem_types == {"INT64", "FLOAT64"}:
            return "LIST<FLOAT64>"
        return "LIST_MIXED"
    return "STRING"


def widen_types(observed: dict[str, int], *, has_large_int: bool = False) -> tuple[str, bool]:
    """Resolve observed type counts into a Spanner column type and conflict flag.

    Returns (spanner_type, is_conflict).
    Homogeneous scalar lists resolve to 'ARRAY<T>' (staged as JSON in CSV/01 DDL).
    """
    types = set(observed.keys()) - {"NULL"}
    if not types:
        return "STRING(MAX)", False

    if len(types) == 1:
        only = next(iter(types))
        if only == "BOOL":
            return "BOOL", False
        if only == "INT64":
            return "INT64", False
        if only == "FLOAT64":
            return "FLOAT64", False
        if only == "STRING":
            return "STRING(MAX)", False
        if only == "DATE":
            return "DATE", False
        if only == "DATETIME":
            return "TIMESTAMP", False
        if only in ("TIME", "DURATION"):
            return "STRING(MAX)", False
        if only == "BYTES":
            return "BYTES(MAX)", False
        if only in ("POINT", "MAP", "LIST_MIXED", "LIST_EMPTY"):
            return "JSON", False
        if only in SCALAR_LIST_TYPES:
            elem = SCALAR_LIST_TYPES[only]
            return f"ARRAY<{elem}>", False

    # Multiple observed types
    if types == {"INT64", "FLOAT64"}:
        if has_large_int:
            return "STRING(MAX)", True
        return "FLOAT64", True

    if "STRING" in types:
        return "STRING(MAX)", True

    if types <= {"TIME", "DURATION"}:
        return "STRING(MAX)", True

    # List combinations
    non_empty_list_types = {t for t in types if t.startswith("LIST<") or t == "LIST_MIXED"}
    if types <= (non_empty_list_types | {"LIST_EMPTY"}):
        if "LIST_MIXED" in types:
            return "JSON", True
        if non_empty_list_types == {"LIST<INT64>", "LIST<FLOAT64>"}:
            return "ARRAY<FLOAT64>", True
        if len(non_empty_list_types) == 1:
            only_list = next(iter(non_empty_list_types))
            elem = SCALAR_LIST_TYPES[only_list]
            return f"ARRAY<{elem}>", False
        # e.g. LIST<INT64> + LIST<STRING>
        return "JSON", True

    if types <= {"POINT", "MAP", "LIST_MIXED", "LIST_EMPTY"}:
        return "JSON", True

    # Any other incompatible mix (e.g. BOOL + INT64, DATE + INT64)
    return "STRING(MAX)", True


def is_array_type(spanner_type: str) -> bool:
    """Return True if the resolved Spanner type is ARRAY<T>."""
    return spanner_type.startswith("ARRAY<") and spanner_type.endswith(">")


def array_element_type(spanner_type: str) -> str:
    """Extract T from ARRAY<T>."""
    if not is_array_type(spanner_type):
        raise ValueError(f"Not an array type: {spanner_type}")
    return spanner_type[len("ARRAY<") : -1]


def staging_spanner_type(spanner_type: str) -> str:
    """Return the Spanner DDL type used during initial CSV load (01_create_tables.sql)."""
    if is_array_type(spanner_type):
        return "JSON"
    return spanner_type


def staging_column_name(spanner_column: str, spanner_type: str) -> str:
    """Return the column name used in 01_create_tables.sql and Dataflow manifests."""
    if is_array_type(spanner_type):
        return f"{spanner_column}__json"
    return spanner_column


def manifest_type_name(spanner_type: str) -> str:
    """Convert a Spanner DDL type to the Dataflow GCS_Text_to_Cloud_Spanner manifest type_name."""
    staged = staging_spanner_type(spanner_type)
    if staged == "STRING(MAX)":
        return "STRING"
    if staged == "BYTES(MAX)":
        return "BYTES"
    return staged
