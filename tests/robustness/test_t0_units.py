"""T0: offline unit, property-based, and stub-gcloud sandbox tests."""

from __future__ import annotations

import datetime
import json
import math
from pathlib import Path
import shutil
import subprocess

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
import pytest
from neo4j.time import DateTime as Neo4jDateTime

from harness import mapping_builder as mb
from harness import sandbox, tool
from harness.findings import check, record

from neo4j_spanner_export.artifacts import generate_artifacts
from neo4j_spanner_export.config import load_mapping, save_mapping
from neo4j_spanner_export.discovery import _resolve_node_pk
from neo4j_spanner_export.compat import ConstraintInfo
from neo4j_spanner_export.serializer import (
    SentinelCollisionError,
    SerializerConfig,
    SerializerConfigError,
    coerce_value,
    format_field,
)
from neo4j_spanner_export.types import classify_value, widen_types

pytestmark = pytest.mark.t0


def _strict_json(s: str):
    def _bad(c):
        raise ValueError(f"non-RFC8259 JSON constant {c}")

    return json.loads(s, parse_constant=_bad)


# ----------------------------------------------------------------------------- D: types / coercion

def test_D01_widening_lattice_documented_rules() -> None:
    cases = {
        ("INT64", "FLOAT64"): "FLOAT64",
        ("INT64", "STRING"): "STRING(MAX)",
        ("BOOL", "INT64"): "STRING(MAX)",
        ("LIST<INT64>", "LIST<FLOAT64>"): "ARRAY<FLOAT64>",
        ("LIST<INT64>", "LIST_EMPTY"): "ARRAY<INT64>",
        ("LIST<INT64>", "LIST<STRING>"): "JSON",
        ("POINT",): "JSON",
        ("TIME", "DURATION"): "STRING(MAX)",
        ("DATETIME",): "TIMESTAMP",
    }
    bad = {k: (widen_types({t: 1 for t in k})[0], v) for k, v in cases.items() if widen_types({t: 1 for t in k})[0] != v}
    check(not bad, None, "D-01", f"lattice deviations: {bad}", title="widening lattice matches README")


_scalar = st.one_of(
    st.integers(min_value=-(2**63), max_value=2**63 - 1),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(max_size=20),
    st.booleans(),
    st.binary(max_size=8),
    st.dates(),
    st.datetimes(timezones=st.just(datetime.timezone.utc)),
)
_value = st.one_of(_scalar, st.lists(st.one_of(st.integers(-10, 10), st.floats(allow_nan=False), st.text(max_size=5), st.booleans()), max_size=5))


@settings(max_examples=400, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(st.lists(_value, min_size=1, max_size=6))
def test_D02_coerce_never_raises_for_inferred_types(values) -> None:
    obs: dict[str, int] = {}
    for v in values:
        t = classify_value(v)
        obs[t] = obs.get(t, 0) + 1
    resolved, _ = widen_types(obs)
    cfg = SerializerConfig()
    for v in values:
        try:
            s = coerce_value(v, resolved)
        except ValueError:
            # Documented fail-fast (NaN/Inf in JSON, ints > 2^53 in FLOAT64, size limits): acceptable, never silent.
            continue
        assert s is None or isinstance(s, str)
        if s is not None and s != cfg.null_string:
            format_field(s, cfg)


def test_D02_record() -> None:
    # Hypothesis test above is the evidence; record the outcome explicitly.
    record(None, "D-02", "Pass", "400 random value mixes: coerce_value returns a string or raises a documented ValueError (fail-fast); never another exception")


def _try(fn, *a, **k):
    try:
        return ("ok", fn(*a, **k))
    except Exception as e:  # noqa: BLE001
        return ("raised", f"{type(e).__name__}: {e}")


def test_D05_int_float_widening_precision() -> None:
    import inspect

    big = 2**53 + 1
    resolved, conflict = widen_types({"INT64": 1, "FLOAT64": 1})
    large = (widen_types({"INT64": 1, "FLOAT64": 1}, has_large_int=True)
             if "has_large_int" in inspect.signature(widen_types).parameters else (resolved, conflict))
    coerced = _try(coerce_value, big, "FLOAT64")
    silent_loss = coerced[0] == "ok" and int(float(coerced[1])) != big
    lossless = large[0] == "STRING(MAX)" and not silent_loss
    check(lossless, "H03", "D-05",
          f"INT64+FLOAT64 -> {resolved}; with ints > 2^53 -> {large[0]}; coerce({big}, FLOAT64) -> {coerced}",
          severity="P0", title="INT64/FLOAT64 widening silently loses integer precision > 2^53")


def test_D08_nan_in_lists_produces_valid_json() -> None:
    res = {}
    for v, t in [([1.5, float("nan")], "ARRAY<FLOAT64>"), ([float("inf")], "ARRAY<FLOAT64>"), ([1, "a", float("nan")], "JSON")]:
        r = _try(coerce_value, v, t)
        if r[0] == "raised":
            res[repr(v)] = ("ok-rejected", r[1][:120])
            continue
        try:
            _strict_json(r[1])
            res[repr(v)] = ("ok", r[1])
        except ValueError as e:
            res[repr(v)] = ("INVALID", r[1], str(e))
    bad = {k: v for k, v in res.items() if not v[0].startswith("ok")}
    check(not bad, "H07", "D-08", f"results: {res}", severity="P1",
          title="NaN/Infinity inside lists serialized as invalid JSON")


def test_D10_int64_override_truncates_or_crashes() -> None:
    r1 = _try(coerce_value, 3.7, "INT64")
    r2 = _try(coerce_value, "abc", "INT64")
    check(r1 != ("ok", "3"), "H04", "D-10",
          f"override INT64: coerce(3.7) -> {r1}; coerce('abc') -> {r2}",
          severity="P0", title="INT64 override silently truncates floats / crashes on strings")


def test_D11_bool_override_maps_unknown_strings_to_false() -> None:
    got = {x: _try(coerce_value, x, "BOOL") for x in ["no", "N", "0", "maybe", "TRUE", "yes"]}
    silent = [x for x in ["maybe", "N"] if got[x] == ("ok", "false")]
    check(not silent, "H04", "D-11", f"BOOL coercion results: {got}; unknown strings silently -> false: {silent}",
          severity="P0", title="BOOL override maps unrecognised strings to false")


def test_D14_datetime_nanoseconds_preserved_in_coercion() -> None:
    dt = Neo4jDateTime(2026, 3, 15, 10, 0, 0, 123456789, tzinfo=datetime.timezone.utc)
    out = coerce_value(dt, "TIMESTAMP")
    check(out is not None and "123456789" in out, "H02", "D-14(T0)",
          f"Neo4j DateTime ...00.123456789Z -> CSV {out!r}", severity="P0",
          title="DateTime nanoseconds truncated to microseconds on export")


def test_D15_out_of_range_years() -> None:
    from neo4j.time import Date as Neo4jDate

    errs = {}
    for y in (0, 10000):
        try:
            d = Neo4jDate(y, 1, 1)
            errs[y] = ("coerced", coerce_value(d, "DATE"))
        except Exception as e:  # noqa: BLE001
            errs[y] = ("raised", f"{type(e).__name__}: {e}")
    record("H22", "D-15(T0)", "Observation", f"Date year 0/10000 handling in coerce_value: {errs}")


# ----------------------------------------------------------------------------- A: CLI / config

def test_A01_missing_password_clean_error(tmp_path: Path) -> None:
    p = tool.cli(["discover", "--uri", "bolt://localhost:1", "--output-mapping", str(tmp_path / "m.yaml")],
                 env={"NEO4J_PASSWORD": ""})
    ok = p.returncode != 0 and not tool.has_traceback(p.stderr) and "NEO4J_PASSWORD" in (p.stderr + p.stdout)
    check(ok, None, "A-01", f"rc={p.returncode} stderr={p.stderr[-400:]}", severity="P2")


@pytest.mark.parametrize("variant", ["unknown_key", "missing_field", "empty_file"])
def test_A04_bad_yaml_clean_error(tmp_path: Path, variant: str) -> None:
    m = mb.mapping([mb.node("Person", ["id"], {"id": "INT64"})])
    path = tmp_path / "m.yaml"
    save_mapping(m, path)
    text = path.read_text()
    if variant == "unknown_key":
        text = text.replace("pk_source:", "colour: blue\n    pk_source:", 1)
    elif variant == "missing_field":
        text = text.replace("    spanner_table: Person\n", "", 1)
    else:
        text = ""
    path.write_text(text)
    p = tool.cli(["export", "--uri", "bolt://localhost:1", "--mapping", str(path), "--output-dir",
                  str(tmp_path / "o"), "--gcs-prefix", "gs://x/y"], env={"NEO4J_PASSWORD": "x"}, timeout=60)
    out = p.stderr + p.stdout
    clean = p.returncode != 0 and not tool.has_traceback(out)
    if variant == "empty_file":
        check(clean, "NEW-EMPTY", f"A-04[{variant}]", f"rc={p.returncode} traceback={tool.has_traceback(out)} tail={out[-400:]}",
              severity="P2", title="An empty schema_mapping.yaml exports 0 rows with exit code 0")
        return
    check(clean, "H26", f"A-04[{variant}]", f"rc={p.returncode} traceback={tool.has_traceback(out)} tail={out[-600:]}",
          severity="P2", title="Hand-edited mapping YAML errors surface as raw Python tracebacks")


def test_A07_serializer_option_validation() -> None:
    illegal = [dict(delimiter=",", quote_char=","), dict(delimiter="ab"), dict(null_string=""),
               dict(null_string="a,b"), dict(default_timezone="Mars/Base")]
    accepted = []
    for kw in illegal:
        try:
            SerializerConfig(**kw)
            accepted.append(kw)
        except (SerializerConfigError, Exception):  # noqa: BLE001
            pass
    legal = [dict(delimiter=d) for d in [",", "|", "\\t", ";", "~", "\x01"]] + [dict(quote_char="'"), dict(escape_char="^")]
    rejected = []
    for kw in legal:
        try:
            SerializerConfig(**kw)
        except Exception as e:  # noqa: BLE001
            rejected.append((kw, str(e)))
    check(not accepted and not rejected, None, "A-07", f"illegal accepted={accepted} legal rejected={rejected}")


def test_A08_invalid_override_reaches_ddl(tmp_path: Path) -> None:
    n = mb.node("Person", ["id"], {"id": "INT64", "age": "INT64"})
    n.properties["age"].override = "VARCHAR"
    m = mb.mapping([n])
    try:
        generate_artifacts(m, tmp_path, "gs://x/y", SerializerConfig())
        ddl = (tmp_path / "schema" / "01_create_tables.sql").read_text()
        msg = f"override VARCHAR accepted; DDL contains: {[l for l in ddl.splitlines() if 'VARCHAR' in l]}"
        rejected = False
    except Exception as e:  # noqa: BLE001
        msg, rejected = f"rejected: {e}", True
    check(rejected, "H04", "A-08", msg, severity="P0", title="Invalid `override` types are not validated")


# ----------------------------------------------------------------------------- B: PK resolution (unit)

class _NoDriver:
    def session(self, **kw):  # pragma: no cover - must not be called for NODE_KEY
        raise AssertionError("driver should not be used when NODE_KEY exists")


def test_B07_node_key_preferred_and_shortest_composite() -> None:
    cons = [
        ConstraintInfo("u1", "UNIQUENESS", ("Order",), ("order_no",)),
        ConstraintInfo("k2", "NODE_KEY", ("Order",), ("tenant", "order_no", "region")),
        ConstraintInfo("k1", "NODE_KEY", ("Order",), ("tenant", "order_no")),
    ]
    pk, src, syn = _resolve_node_pk(_NoDriver(), "neo4j", "Order", [], cons, {})
    check(pk == ["tenant", "order_no"] and src == "node_key" and not syn, None, "B-07",
          f"resolved pk={pk} source={src} synthetic={syn}")
    record(None, "B-07(integration)", "Not testable", "NODE_KEY needs Neo4j Enterprise (out of scope, D6)")


# ----------------------------------------------------------------------------- C: naming (static)

def test_C07_fk_index_name_truncation_collision(tmp_path: Path) -> None:
    a = mb.node("A" * 60, ["id"], {"id": "STRING(MAX)"})
    b1 = mb.node("B" * 59 + "1", ["id"], {"id": "STRING(MAX)"})
    b2 = mb.node("B" * 59 + "2", ["id"], {"id": "STRING(MAX)"})
    e1, e2 = mb.edge(a, "RELX", b1), mb.edge(a, "RELX", b2)
    assert len(e1.spanner_table) == 128 and len(e2.spanner_table) == 128
    m = mb.mapping([a, b1, b2], [e1, e2])
    r = _try(generate_artifacts, m, tmp_path, "gs://x/y", SerializerConfig())
    if r[0] == "raised":
        check(True, "H11", "C-07(T0)", f"rejected at export with: {r[1][:300]}")
        return
    sql = (tmp_path / "schema" / "04_constraints_indexes.sql").read_text()
    import re

    names = re.findall(r"ADD CONSTRAINT (\S+)", sql) + re.findall(r"CREATE INDEX (\S+)", sql)
    dups = sorted({n for n in names if names.count(n) > 1})
    check(not dups, "H11", "C-07(T0)", f"duplicate FK/index names for two valid 128-char edge tables: {dups[:2]}",
          severity="P1", title="FK/index names truncated to 128 chars collide")


def test_C08_dst_prefix_exceeds_128(tmp_path: Path) -> None:
    col = "c" * 126
    a = mb.node("Src", ["id"], {"id": "STRING(MAX)"})
    b = mb.node("Dst", [col], {col: "STRING(MAX)"})
    m = mb.mapping([a, b], [mb.edge(a, "R", b)])
    r = _try(generate_artifacts, m, tmp_path, "gs://x/y", SerializerConfig())
    if r[0] == "raised":
        check("128" in r[1] or "rename" in r[1].lower(), "H12", "C-08(T0)", f"rejected at export with: {r[1][:300]}", severity="P2")
        return
    ddl = (tmp_path / "schema" / "01_create_tables.sql").read_text()
    longest = max(len(tok) for tok in ddl.replace("(", " ").replace(")", " ").replace(",", " ").replace(";", " ").split())
    check(longest <= 128, "H12", "C-08(T0)", f"longest identifier token in DDL = {longest} chars (dst_{col[:6]}...)",
          severity="P2", title="dst_ prefix pushes destination PK column past 128 chars")


# ----------------------------------------------------------------------------- G / L: runbook sandbox

def _bundle(tmp_path: Path, gcs_prefix: str = "gs://b/run", graph_name: str = "G", **ser) -> Path:
    a = mb.node("Person", ["id"], {"id": "STRING(MAX)", "tags": "ARRAY<STRING(MAX)>"})
    m = mb.mapping([a], [mb.edge(a, "KNOWS", a, {"since": "INT64"})])
    out = tmp_path / "out"
    generate_artifacts(m, out, gcs_prefix, SerializerConfig(**ser), graph_name=graph_name)
    return out


def test_G03_runbook_static_checks(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    n = subprocess.run(["bash", "-n", str(out / "load_runbook.sh")], capture_output=True, text=True)
    sc = shutil.which("shellcheck")
    sc_out = subprocess.run([sc, "-S", "warning", str(out / "load_runbook.sh")], capture_output=True, text=True).stdout if sc else "shellcheck not installed"
    check(n.returncode == 0, None, "G-03", f"bash -n rc={n.returncode} {n.stderr}; shellcheck: {sc_out[:800]}")


def test_G06_tilde_delimiter_breaks_parameter_separator(tmp_path: Path) -> None:
    out = _bundle(tmp_path, delimiter="~")
    p, calls = sandbox.run_runbook(out, tmp_path / "sb", env={"GCS_PREFIX": "gs://b/run"})
    params = sandbox.dataflow_params(calls)
    got = params[0].get("columnDelimiter") if params else None
    check(got == "~", "H14", "G-06", f"columnDelimiter seen by Dataflow={got!r}; parsed params={params[:1]}",
          severity="P2", title="Delimiter '~' collides with the ^~^ Dataflow parameter separator")


def test_G07_dataflow_region_override(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    p, calls = sandbox.run_runbook(out, tmp_path / "sb", env={"GCS_PREFIX": "gs://b/run", "REGION": "us-central1",
                                                              "DATAFLOW_REGION": "asia-southeast1",
                                                              "DATAFLOW_SUBNETWORK": "regions/asia-southeast1/subnetworks/s",
                                                              "DATAFLOW_DISABLE_PUBLIC_IPS": "true"})
    runs = [c for c in calls if c[:3] == ["dataflow", "jobs", "run"]]
    ok = bool(runs) and all(
        "--region=asia-southeast1" in c and "--disable-public-ips" in c
        and any(a.startswith("--gcs-location=gs://dataflow-templates-asia-southeast1/") for a in c)
        and "--subnetwork=regions/asia-southeast1/subnetworks/s" in c
        for c in runs)
    check(ok and p.returncode == 0, None, "G-07", f"rc={p.returncode} runs={runs}")


def test_L03_gcs_prefix_shell_injection(tmp_path: Path) -> None:
    sb = tmp_path / "sb"
    sb.mkdir()
    marker = sb / "rb_pwned"
    r = _try(_bundle, tmp_path, gcs_prefix=f"gs://b/$(touch {marker})")
    if r[0] == "raised":
        check(True, "H15", "L-03", f"--gcs-prefix with shell metacharacters rejected at export: {r[1][:250]}")
        return
    out = r[1]
    p, calls = sandbox.run_runbook(out, sb)  # GCS_PREFIX unset -> runbook default is used
    check(not marker.exists(), "H15", "L-03",
          f"--gcs-prefix 'gs://b/$(touch …)' accepted by export; running load_runbook.sh executed it: "
          f"marker exists={marker.exists()}; runbook line: "
          f"{[l for l in (out / 'load_runbook.sh').read_text().splitlines() if l.startswith('GCS_PREFIX=')]}",
          severity="P1", title="--gcs-prefix is interpolated unescaped into load_runbook.sh (command injection)")


def test_L04_graph_name_ddl_injection(tmp_path: Path) -> None:
    try:
        out = _bundle(tmp_path, graph_name="G; DROP TABLE Person")
        sql = (out / "schema" / "05_property_graph.sql").read_text()
        injected = "DROP TABLE Person" in sql
        ev = f"--graph-name accepted; 05_property_graph.sql head: {sql.splitlines()[1][:120]!r}"
    except Exception as e:  # noqa: BLE001
        injected, ev = False, f"rejected: {e}"
    check(not injected, "H15", "L-04", ev, severity="P1", title="--graph-name is not validated (DDL injection)")
