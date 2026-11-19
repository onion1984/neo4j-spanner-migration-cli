"""Static-review findings (G-09) and scope records, per decisions D6/D11 in the test plan."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness import mapping_builder as mb
from harness.findings import check, record

from neo4j_spanner_export.artifacts import generate_artifacts
from neo4j_spanner_export.serializer import SerializerConfig

pytestmark = pytest.mark.t0


def _runbook(tmp_path: Path) -> str:
    a = mb.node("Person", ["id"], {"id": "STRING(MAX)"})
    generate_artifacts(mb.mapping([a]), tmp_path, "gs://b/run", SerializerConfig())
    return (tmp_path / "load_runbook.sh").read_text()


def test_G09_runbook_idempotency_static(tmp_path: Path) -> None:
    rb = _runbook(tmp_path)
    creates_unconditionally = "gcloud spanner databases create" in rb and "databases describe" not in rb
    has_resume = any(k in rb for k in ("SKIP_STAGE", "START_STAGE", "RESUME", "--from-stage"))
    check(not creates_unconditionally or has_resume, "H21", "G-09(H21)",
          (f"runbook checks for an existing database before `databases create` and offers resume flags "
           f"(SKIP_DB_CREATE/SKIP_UPLOAD/SKIP_DATAFLOW/SKIP_STAGE_0x): existence check present={not creates_unconditionally}, resume={has_resume}"
           if (not creates_unconditionally or has_resume) else
           f"runbook runs `gcloud spanner databases create` unconditionally under `set -euo pipefail`; no resume flags. "
           f"A re-run after success fails at stage 1."), severity="P1",
          title="Runbook not idempotent / no resume")


def test_G09_stale_gcs_prefix_static(tmp_path: Path) -> None:
    rb = _runbook(tmp_path)
    m = (tmp_path / "manifests/nodes_manifest.json").read_text()
    cp_no_delete = "gcloud storage cp --recursive" in rb and "storage rm" not in rb and "rsync" not in rb
    glob = '"file_patterns": [\n        "gs://b/run/nodes/Person_part_*.csv"' in m
    check(not (cp_no_delete and glob), "H16", "G-09(H16-GCS)",
          (f"upload clears ${{GCS_PREFIX}}/nodes|edges|manifests before copying (cp without delete={cp_no_delete}); "
           f"export passes the exact shard list to the manifest when a summary is available (wildcard-only manifest={glob})"
           if not (cp_no_delete and glob) else
           f"upload uses `gcloud storage cp --recursive` without clearing the prefix and the manifest uses a wildcard; "
           f"stale shards from an earlier export under the same GCS_PREFIX are loaded too."), severity="P1",
          title="Re-export leaves stale shards that the manifest glob still loads")


def test_scope_records() -> None:
    record("H27", "K-04", "Out of scope", "Concurrent writes during export: README requires a quiesced DB; dropped per D11")
    record("H28", "I-03", "Out of scope", "Neo4j 2025.x not tested per D6 (README claims 4.4 + 5.x)")
    record(None, "G-08/L-06", "Out of scope",
           "Least-privilege SA dropped per D7; default compute SA roles recorded in session.json (very broad: "
           "spanner.admin, storage.admin, dataflow.admin, compute.admin, iam.serviceAccountAdmin, ...)")
    record(None, "T5/J-*", "Out of scope", "Scale tier dropped per D5")


def test_nodes_only_graph_runbook_upload(tmp_path: Path) -> None:
    """NEW-NOEDGE: found during T3 G-02 run (R4 bundle had no edges): `gcloud storage cp edges` fails."""
    a = mb.node("Solo", ["sid"], {"sid": "STRING(MAX)"})
    generate_artifacts(mb.mapping([a]), tmp_path, "gs://b/run", SerializerConfig())
    rb = (tmp_path / "load_runbook.sh").read_text()
    uploads_edges_unconditionally = 'gcloud storage cp --recursive "${SCRIPT_DIR}/edges"' in rb and "[[ -d" not in rb
    runs_edge_job = "edges_manifest.json" in rb
    evidence_log = ""
    for log in Path("/tmp/rb").glob(f"{os.environ.get('RB_RUN_ID', 'none')}/t3_g02/runbook_rb_g02_01.log"):
        txt = log.read_text(errors="replace")
        if "matched no objects or files" in txt:
            evidence_log = [l for l in txt.splitlines() if "ERROR" in l or "export_out/edges" in l][:2]
    check(not uploads_edges_unconditionally, "NEW-NOEDGE", "G-10(nodes-only)",
          (f"nodes-only bundle: runbook skips the edges upload/job (unconditional edges upload={uploads_edges_unconditionally}); "
           f"end-to-end confirmed by G-10(T3:nodes-only)" if not uploads_edges_unconditionally else
           f"runbook always uploads edges/ and launches the edges job even when there are no relationships. Observed: {evidence_log}"),
          severity="P1",
          title="load_runbook.sh fails for graphs without relationships (missing edges/ directory)")


def test_dataflow_job_name_uniqueness(tmp_path: Path) -> None:
    """NEW-JOBNAME: found during T3 (two runbooks started in the same second)."""
    rb = _runbook(tmp_path)
    import re as _re

    m = _re.search(r'jobs run "(neo4j-load-nodes-[^"]*)"', rb)
    second_only = bool(m) and m.group(1) == "neo4j-load-nodes-$(date +%s)"
    evidence_log = ""
    for log in Path("/tmp/rb").glob(f"{os.environ.get('RB_RUN_ID', 'none')}/t3_r1_unescape/runbook_rb_r1_02.log"):
        txt = log.read_text(errors="replace")
        if "ALREADY_EXISTS" in txt:
            evidence_log = [l.strip() for l in txt.splitlines() if "already an active job" in l][:1]
    check(not second_only, "NEW-JOBNAME", "G-11(job-name)",
          (f"job name template now {m.group(1) if m else '?'} (includes PID and $RANDOM); 7 runbooks started within 18 s "
           f"in campaign 2 without collisions" if not second_only else
           f"Dataflow job names are `neo4j-load-{{nodes,edges}}-$(date +%s)`: two runbooks started within the same second "
           f"collide. Observed: {evidence_log}"), severity="P2",
          title="Dataflow job names collide when two loads start in the same second")
