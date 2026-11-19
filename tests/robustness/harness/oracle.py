"""Independent oracle: compares Spanner contents to expected values WITHOUT importing the tool.

Only reads the generated schema_mapping.yaml as *data* (to learn table/column names).
Expected values are expressed in a canonical form:
  STRING -> str, INT64 -> int, FLOAT64 -> float (bit-exact; an int expected value means "exact integer"),
  BOOL -> bool, BYTES -> bytes, DATE -> 'YYYY-MM-DD', TIMESTAMP -> ('ts', epoch_seconds, nanos),
  JSON -> parsed python object, ARRAY<T> -> list of canonical elements, NULL -> None.
"""

from __future__ import annotations

import base64
import datetime
import json
import math
from pathlib import Path
import struct
from typing import Any

import yaml

_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)


def load_mapping_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def ts(epoch_s: int, nanos: int = 0) -> tuple:
    return ("ts", int(epoch_s), int(nanos))


def ts_from_iso(s: str) -> tuple:
    """Parse 'YYYY-MM-DDTHH:MM:SS[.fffffffff]Z' exactly (ns precision) -> ('ts', s, ns)."""
    assert s.endswith("Z")
    main, _, frac = s[:-1].partition(".")
    dt = datetime.datetime.strptime(main, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    secs = (dt - _EPOCH) // datetime.timedelta(seconds=1)
    ns = int((frac + "000000000")[:9]) if frac else 0
    return ts(secs, ns)


def norm_spanner(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, datetime.datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=datetime.timezone.utc)
        ns = getattr(v, "nanosecond", None)
        base = v.replace(microsecond=0)
        secs = (base - _EPOCH) // datetime.timedelta(seconds=1)
        if ns is None or (ns == 0 and v.microsecond):
            ns = v.microsecond * 1000
        return ts(secs, ns)
    if isinstance(v, datetime.date):
        return v.isoformat()
    if hasattr(v, "serialize") and callable(v.serialize):  # JsonObject
        s = v.serialize()
        return None if s is None else json.loads(s)
    if isinstance(v, (bytes, bytearray)):
        return base64.b64decode(v)
    if isinstance(v, list):
        return [norm_spanner(x) for x in v]
    return v


def _float_eq(a: float, b: Any) -> bool:
    if isinstance(b, bool):
        return False
    if isinstance(b, int):  # exact-integer expectation
        return a == b and float(b) == a and int(a) == b
    if math.isnan(a) and math.isnan(b):
        return True
    return struct.pack(">d", a) == struct.pack(">d", float(b))


def values_equal(actual: Any, expected: Any) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if isinstance(actual, float):
        return _float_eq(actual, expected)
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(values_equal(a, e) for a, e in zip(actual, expected))
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(values_equal(actual[k], expected[k]) for k in actual)
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    return actual == expected


def expected_from_neo4j(v: Any, spanner_type: str) -> Any:
    """Independent converter (README rules) from a Neo4j driver value to the canonical expected form.

    Only used for R1/R3; does not import the tool. `spanner_type` is read from schema_mapping.yaml.
    """
    from neo4j.spatial import Point
    from neo4j.time import Date, DateTime, Duration, Time

    if v is None:
        return None
    if spanner_type.startswith("ARRAY<"):
        elem = spanner_type[6:-1]
        return [expected_from_neo4j(x, elem) for x in v]
    if isinstance(v, DateTime) and spanner_type == "TIMESTAMP":
        if v.tzinfo is None:
            v = v.replace(tzinfo=datetime.timezone.utc)
        native = v.to_native()
        secs = (native.replace(microsecond=0) - _EPOCH) // datetime.timedelta(seconds=1)
        return ts(secs, v.nanosecond)
    if isinstance(v, Date) and spanner_type == "DATE":
        return v.iso_format()
    if isinstance(v, Point):
        d = {"srid": v.srid, "x": float(v.x), "y": float(v.y)}
        if len(v) > 2:
            d["z"] = float(v.z)
        return d
    if isinstance(v, (bytes, bytearray)):
        return bytes(v)
    if spanner_type in ("STRING", "STRING(MAX)"):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (Date, DateTime, Time, Duration)):
            return str(v.iso_format())
        return str(v)
    if spanner_type == "JSON":
        if isinstance(v, list):
            return [expected_from_neo4j(x, "JSON") for x in v]
        if isinstance(v, (Date, DateTime, Time, Duration)):
            return v.iso_format()
        return v
    return v


def _short(v: Any) -> str:
    r = repr(v)
    return r if len(r) < 200 else r[:120] + f"...<{len(r)} chars>"


def compare_table(query_fn, mapping: dict[str, Any], label: str, key_cols: list[str],
                  expected_rows: dict[tuple, dict[str, Any]], exact_rowcount: bool = True) -> list[dict[str, Any]]:
    """query_fn(sql) -> list[dict]. Expected keys/cols are *raw Neo4j property names*."""
    nm = mapping["nodes"][label]
    table = nm["spanner_table"]
    cols = {raw: p["spanner_column"] for raw, p in nm["properties"].items()}
    wanted = sorted({c for row in expected_rows.values() for c in row} | set(key_cols))
    sel = ", ".join(cols[c] for c in wanted)
    rows = query_fn(f"SELECT {sel} FROM {table}")
    by_key: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        nr = {raw: norm_spanner(r[cols[raw]]) for raw in wanted}
        by_key[tuple(nr[k] if not isinstance(nr[k], list) else tuple(nr[k]) for k in key_cols)] = nr
    diffs: list[dict[str, Any]] = []
    for key, exp in expected_rows.items():
        got = by_key.get(key)
        if got is None:
            diffs.append({"table": label, "key": _short(key), "error": "missing_in_spanner"})
            continue
        for col, ev in exp.items():
            if not values_equal(got[col], ev):
                diffs.append({"table": label, "key": _short(key), "column": col,
                              "expected": _short(ev), "actual": _short(got[col])})
    if exact_rowcount and len(rows) != len(expected_rows):
        diffs.append({"table": label, "error": f"rowcount spanner={len(rows)} expected={len(expected_rows)}"})
    return diffs
