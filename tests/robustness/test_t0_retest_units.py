"""T0 unit-level re-tests for defects whose integration tests are blocked by NEW-DISCCRASH (campaign 2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness import mapping_builder as mb
from harness.findings import check

from neo4j_spanner_export.artifacts import generate_artifacts
from neo4j_spanner_export.serializer import SerializerConfig, coerce_value

pytestmark = pytest.mark.t0


def _try(fn, *a, **k):
    try:
        return ("ok", fn(*a, **k))
    except Exception as e:  # noqa: BLE001
        return ("raised", f"{type(e).__name__}: {e}")


def test_NEW_DIGITNAME_unit(tmp_path: Path) -> None:
    n = mb.node("VipCustomer", ["cid"], {"cid": "STRING(MAX)", "1st": "INT64"})
    n.properties["1st"].spanner_column = "id_1st"
    r1 = _try(generate_artifacts, mb.mapping([n]), tmp_path / "a", "gs://x/y", SerializerConfig())
    n.column_renames = {"1st": "first_x"}
    r2 = _try(generate_artifacts, mb.mapping([n]), tmp_path / "b", "gs://x/y", SerializerConfig())
    graph = (tmp_path / "b" / "schema" / "05_property_graph.sql").read_text() if r2[0] == "ok" else ""
    ok = r1[0] == "raised" and "1st" in r1[1] and "rename" in r1[1].lower() and "AS `first_x`" in graph
    check(ok, "NEW-DIGITNAME", "C-05(T0)",
          f"property '1st' without rename -> {r1[1] if r1[0] == 'raised' else 'accepted'}; with column_renames 1st->first_x -> "
          f"{'graph alias `first_x` emitted' if 'AS `first_x`' in graph else r2}", severity="P1",
          title="Original property/label names starting with a digit break CREATE PROPERTY GRAPH")


def test_NEW_MONO_unit() -> None:
    from neo4j_spanner_export.discovery import _looks_monotonic
    import uuid

    desc = list(range(50, 0, -1))
    shuffled = [7, 3, 9, 1, 10, 2, 8, 4, 6, 5, 12, 11]
    rnd = [str(uuid.uuid4()) for _ in range(50)]
    res = {"descending_ints": _looks_monotonic(desc), "shuffled_dense_ints": _looks_monotonic(shuffled),
           "random_uuids": _looks_monotonic(rnd)}
    check(res["descending_ints"] and res["shuffled_dense_ints"] and not res["random_uuids"], "NEW-MONO", "B-15(T0)",
          f"_looks_monotonic results (scan-order independent expected): {res}", severity="P2",
          title="Monotonic-PK hotspot warning depends on Neo4j scan order")


def test_NEW_SIZE_unit() -> None:
    s = _try(coerce_value, "x" * 2_700_000, "STRING(MAX)")
    b = _try(coerce_value, b"\x00" * (10 * 1024 * 1024 + 1), "BYTES(MAX)")
    j = _try(coerce_value, ["y" * 2_700_000], "ARRAY<STRING(MAX)>")
    emoji = _try(coerce_value, "\U0001F600" * 2_600_000, "STRING(MAX)")
    ok = all(r[0] == "raised" for r in (s, b, j))
    check(ok, "NEW-SIZE", "E-07(T0)",
          f"2.7M-char STRING -> {s[0]} ({s[1] if s[0] == 'raised' else ''}); 10 MiB+1 BYTES -> {b[0]}; 2.7M-char ARRAY JSON -> {j[0]}; "
          f"2.6M 4-byte chars (10.4 MB) -> {emoji[0]} (accepted by Spanner in R5, 2/2 rows)", severity="P2",
          title="Values above Spanner limits (STRING 2,621,440 chars / 10 MiB) are not detected before load")


@pytest.mark.t1
def test_H18_type_drift_export_level(neo4j_v5, work_dir) -> None:
    """A-06 equivalent without discovery: mapping says INT64, data later contains a string."""
    from harness import neo4j_util as nu
    from harness import tool

    nu.wipe(neo4j_v5)
    nu.unique(neo4j_v5, "Dr", "did")
    nu.run(neo4j_v5, "UNWIND range(1,20) AS i CREATE (:Dr {did: i, v: i})")
    nu.run(neo4j_v5, "CREATE (:Dr {did: 999, v: 'not-a-number'})")
    m = mb.mapping([mb.node("Dr", ["did"], {"did": "INT64", "v": "INT64"})])
    try:
        tool.export(neo4j_v5, work_dir, m)
        ok, ev = False, "export succeeded silently with drifted types"
    except Exception as e:  # noqa: BLE001
        out = work_dir / "export_out"
        files = sorted(p.name for p in out.rglob("*") if p.is_file()) if out.exists() else []
        ok, ev = not files, f"export raised {type(e).__name__}: {str(e)[:160]}; partial files left: {files}"
    check(ok, "H18", "A-06(T1,manual-mapping)", ev, severity="P1",
          title="--sample-size type drift crashes export mid-stream and leaves a partial bundle")


def test_NEW_SILENTREJECT_runbook_fails_on_invalid_records(tmp_path: Path) -> None:
    """Stub gcloud reports one object under invalid_records/ -> runbook must stop with a non-zero exit."""
    import os
    import subprocess

    a = mb.node("Person", ["id"], {"id": "STRING(MAX)"})
    out = tmp_path / "out"
    generate_artifacts(mb.mapping([a]), out, "gs://b/run", SerializerConfig())
    (out / "nodes").mkdir(exist_ok=True)
    (out / "nodes" / "Person_part_00000.csv").write_text("p1\n")
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "gcloud").write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  *"invalid_records"*) [[ "$1 $2" == "storage ls" ]] && echo "gs://b/run/invalid_records/nodes/bad-00000.csv" ;;\n'
        '  *"dataflow jobs run"*) echo fake-job ;;\n'
        '  *"dataflow jobs describe"*) echo JOB_STATE_DONE ;;\n'
        '  *"databases describe"*) exit 1 ;;\n'
        "esac\nexit 0\n")
    (stub / "gcloud").chmod(0o755)
    env = dict(os.environ, PATH=f"{stub}:{os.environ['PATH']}", GCS_PREFIX="gs://b/run", PROJECT_ID="p", INSTANCE="i", DATABASE="d")
    p = subprocess.run(["bash", str(out / "load_runbook.sh")], capture_output=True, text=True, env=env, timeout=60)
    ok = p.returncode != 0 and "rejected rows" in p.stderr and "Load complete" not in p.stdout
    check(ok, "NEW-SILENTREJECT", "G-12(sandbox)",
          f"stub reports 1 object under invalid_records/nodes: runbook rc={p.returncode}; stderr={p.stderr.strip()[-200:]!r}; "
          f"'Load complete!' printed={'Load complete' in p.stdout}", severity="P1",
          title="Rows rejected by Dataflow are written to invalid_records/ but the runbook still reports success")
