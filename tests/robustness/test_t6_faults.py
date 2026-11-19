"""T6: local fault injection & recovery (D11: local only)."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import signal
import subprocess
import time

import pytest

from harness import mapping_builder as mb
from harness import neo4j_util as nu
from harness import tool
from harness.findings import check, record

pytestmark = [pytest.mark.t6, pytest.mark.timeout(900)]

PW = "testpassword123"
N_BULK = 300_000


def _ensure_bulk(d) -> None:
    if nu.run(d, "MATCH (n:Bulk) RETURN count(n) AS c")[0]["c"] == N_BULK and nu.counts(d)[0] == N_BULK:
        return
    nu.wipe(d)
    nu.unique(d, "Bulk", "bk")
    for i in range(0, N_BULK, 50_000):
        nu.run(d, "UNWIND range($a, $b) AS i CREATE (:Bulk {bk: i, payload: 'p' + toString(i), f: toFloat(i) / 3})", a=i, b=min(i + 49_999, N_BULK - 1))


@pytest.fixture
def bulk_mapping(neo4j_v5, work_root):
    d = neo4j_v5
    _ensure_bulk(d)
    w = work_root / "bulk_mapping"
    w.mkdir(parents=True, exist_ok=True)
    tool.discover_or_manual(d, w, mb.mapping([mb.node("Bulk", ["bk"], {"bk": "INT64", "payload": "STRING(MAX)", "f": "FLOAT64"})]))
    return w / "schema_mapping.yaml"


def _export_proc(mapping: Path, out: Path, chunk: int = 20_000) -> subprocess.Popen:
    env = dict(os.environ, NEO4J_PASSWORD=PW)
    return subprocess.Popen(tool.CLI + ["export", "--uri", "bolt://localhost:7687", "--mapping", str(mapping),
                                        "--output-dir", str(out), "--gcs-prefix", "gs://x/y", "--chunk-rows", str(chunk)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)


def _wait_for_shards(out: Path, n: int = 1, timeout: float = 60) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if len(list((out / "nodes").glob("*.csv"))) >= n:
            return
        time.sleep(0.2)


def test_K01_neo4j_pause_mid_export(bulk_mapping, work_dir, neo4j_v5):
    out = work_dir / "out"
    p = _export_proc(bulk_mapping, out)
    _wait_for_shards(out, 2)
    subprocess.run(["podman", "pause", "neo4j-v5"], check=True)
    t0 = time.time()
    try:
        p.wait(timeout=180)
        hung, elapsed = False, time.time() - t0
    except subprocess.TimeoutExpired:
        hung, elapsed = True, time.time() - t0
    finally:
        subprocess.run(["podman", "unpause", "neo4j-v5"], check=False)
        if p.poll() is None:
            p.kill()
        tail = (p.stdout.read() or "")[-400:]
    nu.wait_ready(neo4j_v5)
    check(not hung and p.returncode != 0, "H24", "K-01",
          f"after `podman pause`, export {'still running after' if hung else 'exited after'} {elapsed:.0f}s rc={p.returncode} tail={tail!r}",
          severity="P1", title="Export hangs indefinitely when Neo4j stalls (no driver timeout)")


def test_K02_neo4j_restart_mid_export(bulk_mapping, work_dir, neo4j_v5):
    out = work_dir / "out"
    p = _export_proc(bulk_mapping, out)
    _wait_for_shards(out, 2)
    subprocess.run(["podman", "restart", "neo4j-v5"], check=True, capture_output=True)
    try:
        p.wait(timeout=300)
    except subprocess.TimeoutExpired:
        p.kill()
    tail = (p.stdout.read() or "")
    nu.wait_ready(neo4j_v5)
    shards = sorted((out / "nodes").glob("*.csv"))
    rows = sum(len(s.read_text().splitlines()) for s in shards)
    has_artifacts = (out / "load_runbook.sh").exists()
    ok = p.returncode != 0 and not has_artifacts
    check(ok, "H24", "K-02",
          f"rc={p.returncode} traceback={tool.has_traceback(tail)} rows_written={rows}/{N_BULK} artifacts_generated={has_artifacts}",
          severity="P1", title="Export hangs indefinitely when Neo4j stalls (no driver timeout)")
    record("NEW-UX", "K-02(ux)", "Observation", f"restart error surfaced as: {tail.strip().splitlines()[-1][:200] if tail.strip() else ''}")


def test_K03_zero_row_table(neo4j_v5, work_dir):
    d = neo4j_v5
    nu.wipe(d)
    nu.unique(d, "Keep", "kk")
    nu.run(d, "CREATE (:Keep {kk:1}), (:Gone {gg:1})")
    gone = mb.node("Gone", ["_neo4j_id"], {"_neo4j_id": "INT64", "gg": "INT64"})
    gone.is_synthetic_pk = True
    gone.properties["_neo4j_id"].spanner_column = "id__neo4j_id"
    m = tool.discover_or_manual(d, work_dir, mb.mapping([mb.node("Keep", ["kk"], {"kk": "INT64"}), gone]))
    nu.run(d, "MATCH (n:Gone) DELETE n")
    b = tool.export(d, work_dir, m)
    shards = list((b.out_dir / "nodes").glob("Gone_part_*.csv"))
    manifest = (b.out_dir / "manifests/nodes_manifest.json").read_text()
    ok = bool(shards) or ('"Gone"' not in manifest)
    check(ok, "H17", "K-03",
          f"0-row table: shards={len(shards)}, manifest references table Gone: {'\"Gone\"' in manifest}; "
          f"Dataflow behaviour on an empty glob not tested (GCP fault tests out of scope)",
          severity="P2", title="0-row tables produce a manifest glob that matches no files")


def test_K05_stale_shards_on_reexport(neo4j_v5, work_dir):
    d = neo4j_v5
    nu.wipe(d)
    nu.unique(d, "St", "sid")
    nu.run(d, "UNWIND range(1,6) AS i CREATE (:St {sid:i})")
    m = tool.discover_or_manual(d, work_dir, mb.mapping([mb.node("St", ["sid"], {"sid": "INT64"})]))
    tool.export(d, work_dir, m, chunk_rows=1)
    nu.run(d, "MATCH (s:St) WHERE s.sid > 2 DELETE s")
    try:
        b = tool.export(d, work_dir, m, chunk_rows=1)
    except FileExistsError as e:
        refused = str(e)
        b2 = tool.export(d, work_dir, m, chunk_rows=1, overwrite=True)
        rows2 = len(tool.all_csv_lines(b2.out_dir, "nodes", "St"))
        check(rows2 == b2.summary.nodes["St"].row_count == 2, "H16", "K-05",
              f"re-export into non-empty dir refused: {refused[:160]}; with --overwrite: {rows2} rows on disk = summary {b2.summary.nodes['St'].row_count}")
        return
    shards = sorted(p.name for p in (b.out_dir / "nodes").glob("St_part_*.csv"))
    rows = len(tool.all_csv_lines(b.out_dir, "nodes", "St"))
    check(rows == b.summary.nodes["St"].row_count, "H16", "K-05",
          f"second export reported {b.summary.nodes['St'].row_count} rows but {len(shards)} shards / {rows} rows match the manifest glob ({shards})",
          severity="P1", title="Re-export leaves stale shards that the manifest glob still loads")


def test_K07_disk_full(neo4j_v5, work_dir, monkeypatch):
    d = neo4j_v5
    nu.wipe(d)
    nu.run(d, "UNWIND range(1,100) AS i CREATE (:Df {x:i})")
    nu.unique(d, "Df", "x")
    m = tool.discover_or_manual(d, work_dir, mb.mapping([mb.node("Df", ["x"], {"x": "INT64"})]))
    from neo4j_spanner_export import writer

    real = writer.ShardedDelimitedWriter.write_row
    calls = {"n": 0}

    def boom(self, fields, pk=None):
        calls["n"] += 1
        if calls["n"] > 10:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(self, fields, pk)

    monkeypatch.setattr(writer.ShardedDelimitedWriter, "write_row", boom)
    try:
        tool.export(d, work_dir, m)
        ok, ev = False, "ENOSPC swallowed; export reported success"
    except OSError as e:
        has_art = (work_dir / "export_out" / "load_runbook.sh").exists()
        ok, ev = (e.errno == errno.ENOSPC and not has_art), f"OSError propagated: {e}; artifacts generated={has_art}"
    check(ok, None, "K-07", ev, severity="P2")


def test_K10_kill_mid_shard(bulk_mapping, work_dir, neo4j_v5):
    # (a) fresh dir killed -> must not look like a complete bundle
    out = work_dir / "fresh"
    p = _export_proc(bulk_mapping, out, chunk=2_000)
    _wait_for_shards(out, 3)
    p.send_signal(signal.SIGKILL)
    p.wait()
    fresh_complete_looking = (out / "load_runbook.sh").exists() or (out / "manifests").exists()
    # (b) re-run into a dir that already holds a complete bundle, killed mid-way
    out2 = work_dir / "rerun"
    p0 = _export_proc(bulk_mapping, out2)
    p0.wait(timeout=600)
    first_rows = sum(len(s.read_text().splitlines()) for s in (out2 / "nodes").glob("*.csv"))
    p2 = _export_proc(bulk_mapping, out2, chunk=2_000)
    time.sleep(4.0)
    p2.send_signal(signal.SIGKILL)
    p2.wait()
    shards = sorted((out2 / "nodes").glob("*.csv"))
    rows = sum(len(s.read_text().splitlines()) for s in shards)
    truncated = [s.name for s in shards if s.stat().st_size and not s.read_bytes().endswith(b"\n")]
    looks_complete = (out2 / "load_runbook.sh").exists() and (out2 / "manifests/nodes_manifest.json").exists()
    ok = not fresh_complete_looking and not (looks_complete and (rows != N_BULK or truncated))
    check(ok, "H16", "K-10",
          f"fresh-dir kill leaves complete-looking bundle={fresh_complete_looking}; re-run kill: old runbook/manifests still present={looks_complete}, "
          f"rows on disk={rows}/{N_BULK} (complete first run had {first_rows}), truncated shards={truncated[:3]}",
          severity="P1", title="Interrupted re-export leaves a corrupt but complete-looking bundle")
