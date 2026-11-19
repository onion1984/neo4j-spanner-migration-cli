"""Value coercion, bit-reversal, escaping, and null-sentinel serialization."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import datetime
import json
import math
from typing import Any
from zoneinfo import ZoneInfo

from neo4j.spatial import Point
from neo4j.time import Date as Neo4jDate
from neo4j.time import DateTime as Neo4jDateTime
from neo4j.time import Duration as Neo4jDuration
from neo4j.time import Time as Neo4jTime


from .types import MAX_SAFE_FLOAT64_INT

SPANNER_MAX_STRING_CHARS = 2_621_440
SPANNER_MAX_BYTES_LEN = 10 * 1024 * 1024
EMPTY_BYTES_SENTINEL = b"\x00__NEO4J_EMPTY_BYTES_SENTINEL_V1__\x00"


class SentinelCollisionError(ValueError):
    """Raised when a literal data value equals the configured null sentinel."""


class SerializerConfigError(ValueError):
    """Raised when delimiter / quote / escape / null-sentinel options overlap."""


@dataclass(frozen=True)
class SerializerConfig:
    """Configuration for delimited CSV field serialization."""

    delimiter: str = ","
    null_string: str = "__NULL__"
    quote_char: str = '"'
    escape_char: str = "\\"
    default_timezone: str = "UTC"

    def __post_init__(self) -> None:
        # Normalize literal '\t' passed on CLI to tab char.
        if self.delimiter == "\\t":
            object.__setattr__(self, "delimiter", "\t")
        self.validate()

    def validate(self) -> None:
        if len(self.delimiter) != 1:
            raise SerializerConfigError(f"delimiter must be a single character, got {self.delimiter!r}")
        if len(self.quote_char) != 1:
            raise SerializerConfigError(f"quote_char must be a single character, got {self.quote_char!r}")
        if len(self.escape_char) != 1:
            raise SerializerConfigError(f"escape_char must be a single character, got {self.escape_char!r}")
        if not self.null_string:
            raise SerializerConfigError("null_string must be non-empty")

        chars = {self.delimiter, self.quote_char, self.escape_char}
        if len(chars) < 3:
            raise SerializerConfigError(
                f"delimiter ({self.delimiter!r}), quote_char ({self.quote_char!r}), and "
                f"escape_char ({self.escape_char!r}) must be mutually distinct"
            )
        if self.null_string in chars:
            raise SerializerConfigError("null_string must not equal delimiter, quote_char, or escape_char")
        for c in chars:
            if c in self.null_string:
                raise SerializerConfigError(
                    f"null_string {self.null_string!r} must not contain {c!r}"
                )
        # Validate timezone
        ZoneInfo(self.default_timezone)


def bit_reverse_64(val: int) -> int:
    """Reverse the 64 bits of an integer and return a signed 64-bit integer.

    Used for synthetic _neo4j_id keys so sequential Neo4j internal IDs distribute
    uniformly across Spanner splits.
    """
    u = val & 0xFFFFFFFFFFFFFFFF
    rev = 0
    for _ in range(64):
        rev = (rev << 1) | (u & 1)
        u >>= 1
    if rev >= (1 << 63):
        rev -= 1 << 64
    return rev


def _to_json_compatible(value: Any, default_tz: str) -> Any:
    """Recursively convert Neo4j spatial/temporal/bytes values for JSON serialization."""
    if type(value).__name__ == "BrokenHydrationObject":
        raise ValueError(f"Unsupported or out-of-range Neo4j temporal/hydration value: {value!r}")
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, Point):
        d: dict[str, Any] = {"srid": value.srid, "x": value.x, "y": value.y}
        if hasattr(value, "z") and value.z is not None:
            d["z"] = value.z
        return d
    if isinstance(value, Neo4jDateTime):
        return _format_neo4j_datetime_utc(value, default_tz)
    if isinstance(value, datetime.datetime):
        return _format_datetime_utc(value, default_tz)
    if isinstance(value, Neo4jDate):
        if not (1 <= value.year <= 9999):
            raise ValueError(f"Neo4j Date year out of range (1..9999): {value.year}")
        return value.iso_format()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, Neo4jTime):
        return value.iso_format()
    if isinstance(value, datetime.time):
        return value.isoformat()
    if isinstance(value, Neo4jDuration):
        return value.iso_format()
    if isinstance(value, datetime.timedelta):
        return f"PT{value.total_seconds()}S"
    if isinstance(value, list):
        return [_to_json_compatible(item, default_tz) for item in value]
    if isinstance(value, dict):
        return {str(k): _to_json_compatible(v, default_tz) for k, v in value.items()}
    return str(value)


def _format_datetime_utc(dt: datetime.datetime, default_tz: str) -> str:
    """Format a Python datetime (naive or aware) as UTC RFC3339/ISO-8601 with 'Z'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(default_tz))
    utc_dt = dt.astimezone(datetime.timezone.utc)
    return utc_dt.isoformat().replace("+00:00", "Z")


def _format_neo4j_datetime_utc(dt: Neo4jDateTime, default_tz: str) -> str:
    """Format a Neo4j DateTime as UTC RFC3339/ISO-8601 with 'Z', preserving nanoseconds."""
    if not (1 <= dt.year <= 9999):
        raise ValueError(f"Neo4j DateTime year out of range (1..9999): {dt.year}")
    ns = int(getattr(dt, "nanosecond", 0))
    native = dt.to_native()
    if native.tzinfo is None:
        native = native.replace(tzinfo=ZoneInfo(default_tz))
    utc_dt = native.astimezone(datetime.timezone.utc)
    base = f"{utc_dt.year:04d}-{utc_dt.month:02d}-{utc_dt.day:02d}T{utc_dt.hour:02d}:{utc_dt.minute:02d}:{utc_dt.second:02d}"
    if ns == 0:
        return f"{base}Z"
    return f"{base}.{ns:09d}Z"


def coerce_value(
    value: Any,
    spanner_type: str,
    default_tz: str = "UTC",
    *,
    empty_bytes_sentinel: bytes | None = None,
) -> str | None:
    """Coerce a Neo4j property value into the canonical string representation for CSV.

    Returns None when value is None.
    For ARRAY<T>, coerces to compact JSON string (for <col>__json staging column).
    """
    if value is None:
        return None
    if type(value).__name__ == "BrokenHydrationObject":
        raise ValueError(f"Unsupported or out-of-range Neo4j temporal/hydration value: {value!r}")

    if spanner_type == "INT64":
        if isinstance(value, bool):
            raise ValueError(f"Cannot coerce bool {value!r} to INT64")
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value) or not value.is_integer():
                raise ValueError(f"Cannot coerce non-integer float {value!r} to INT64 without loss")
            return str(int(value))
        return str(int(value))

    if spanner_type == "FLOAT64":
        if isinstance(value, int) and not isinstance(value, bool) and abs(value) > MAX_SAFE_FLOAT64_INT:
            raise ValueError(
                f"Integer {value} exceeds 2^53 precision limit for FLOAT64; use override: STRING(MAX)"
            )
        f = float(value)
        if math.isnan(f):
            return "NaN"
        if math.isinf(f):
            return "Infinity" if f > 0 else "-Infinity"
        return repr(f)

    if spanner_type == "BOOL":
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int) and value in (0, 1):
            return "true" if value == 1 else "false"
        if isinstance(value, str):
            low = value.strip().lower()
            if low in ("true", "1", "yes"):
                return "true"
            if low in ("false", "0", "no"):
                return "false"
            raise ValueError(f"Cannot coerce string {value!r} to BOOL")
        raise ValueError(f"Cannot coerce {type(value).__name__} {value!r} to BOOL")

    if spanner_type == "DATE":
        if isinstance(value, Neo4jDate):
            if not (1 <= value.year <= 9999):
                raise ValueError(f"Neo4j Date year out of range (1..9999): {value.year}")
            return value.iso_format()
        if isinstance(value, datetime.datetime):
            return value.date().isoformat()
        if isinstance(value, datetime.date):
            return value.isoformat()
        return str(value)

    if spanner_type == "TIMESTAMP":
        if isinstance(value, Neo4jDateTime):
            return _format_neo4j_datetime_utc(value, default_tz)
        if isinstance(value, datetime.datetime):
            return _format_datetime_utc(value, default_tz)
        if isinstance(value, Neo4jDate):
            if not (1 <= value.year <= 9999):
                raise ValueError(f"Neo4j Date year out of range (1..9999): {value.year}")
            dt = datetime.datetime(value.year, value.month, value.day, tzinfo=ZoneInfo(default_tz))
            return _format_datetime_utc(dt, default_tz)
        return str(value)

    if spanner_type == "BYTES(MAX)":
        raw_bytes = bytes(value) if isinstance(value, (bytes, bytearray)) else str(value).encode("utf-8")
        if len(raw_bytes) > SPANNER_MAX_BYTES_LEN:
            raise ValueError(
                f"BYTES value of length {len(raw_bytes)} exceeds Spanner 10 MiB limit ({SPANNER_MAX_BYTES_LEN})"
            )
        if raw_bytes == b"" and empty_bytes_sentinel is not None:
            raw_bytes = empty_bytes_sentinel
        return base64.b64encode(raw_bytes).decode("ascii")

    if spanner_type == "JSON" or spanner_type.startswith("ARRAY<"):
        compat_val = _to_json_compatible(value, default_tz)
        try:
            out = json.dumps(compat_val, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        except ValueError as exc:
            raise ValueError(
                f"Cannot serialize {spanner_type} value to RFC8259 JSON (NaN/Infinity is not allowed): {exc}"
            ) from exc
        if len(out) > SPANNER_MAX_STRING_CHARS:
            raise ValueError(
                f"{spanner_type} JSON length {len(out)} exceeds Spanner limit ({SPANNER_MAX_STRING_CHARS})"
            )
        return out

    # STRING(MAX) or fallback
    if isinstance(value, (Neo4jTime, Neo4jDuration)):
        out = value.iso_format()
    elif isinstance(value, Neo4jDate):
        if not (1 <= value.year <= 9999):
            raise ValueError(f"Neo4j Date year out of range (1..9999): {value.year}")
        out = value.iso_format()
    elif isinstance(value, Neo4jDateTime):
        out = _format_neo4j_datetime_utc(value, default_tz)
    elif isinstance(value, (datetime.time, datetime.date, datetime.datetime)):
        out = value.isoformat()
    elif isinstance(value, (bytes, bytearray)):
        out = base64.b64encode(bytes(value)).decode("ascii")
    elif isinstance(value, (list, dict, Point)):
        try:
            out = json.dumps(_to_json_compatible(value, default_tz), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        except ValueError as exc:
            raise ValueError(
                f"Cannot serialize value to RFC8259 JSON (NaN/Infinity is not allowed): {exc}"
            ) from exc
    elif isinstance(value, bool):
        out = "true" if value else "false"
    else:
        out = str(value)

    if len(out) > SPANNER_MAX_STRING_CHARS:
        raise ValueError(
            f"STRING value of length {len(out)} exceeds Spanner STRING(MAX) limit ({SPANNER_MAX_STRING_CHARS} chars)"
        )
    return out


def format_field(
    raw_str: str | None,
    cfg: SerializerConfig,
    table: str = "",
    column: str = "",
    pk: Any = None,
) -> str:
    """Format a coerced string (or None) into a delimited CSV field.

    - None -> bare null_string
    - "" -> quoted empty string ("")
    - literal == null_string -> raises SentinelCollisionError
    - Escapes escape_char -> 2x escape_char, LF -> \\n, CR -> \\r, quote_char -> 2x quote_char
    - Quotes if field contains delimiter, quote_char, or escape_char (which also covers escaped LF/CR)
    """
    if raw_str is None:
        return cfg.null_string

    if raw_str == cfg.null_string:
        raise SentinelCollisionError(
            f"Literal data value equals null sentinel {cfg.null_string!r} "
            f"in {table}.{column} (pk={pk!r}). Choose a different --null-string."
        )

    if raw_str == "":
        return f"{cfg.quote_char}{cfg.quote_char}"

    esc = cfg.escape_char
    q = cfg.quote_char

    escaped = (
        raw_str.replace(esc, esc + esc)
        .replace("\n", esc + "n")
        .replace("\r", esc + "r")
        .replace(q, q + q)
    )

    needs_quotes = (
        cfg.delimiter in escaped
        or q in escaped
        or esc in escaped
    )
    if needs_quotes:
        return f"{q}{escaped}{q}"
    return escaped


def format_row(
    fields: list[str | None],
    cfg: SerializerConfig,
    table: str = "",
    columns: list[str] | None = None,
    pk: Any = None,
) -> str:
    """Format a full row of coerced strings into a single LF-terminated line."""
    col_names = columns or [f"col_{i}" for i in range(len(fields))]
    formatted = [
        format_field(val, cfg, table=table, column=col, pk=pk)
        for val, col in zip(fields, col_names)
    ]
    return cfg.delimiter.join(formatted) + "\n"
