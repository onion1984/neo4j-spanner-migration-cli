"""Stub-gcloud sandbox for running a generated load_runbook.sh without touching GCP (D15)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

_STUB = r"""#!/usr/bin/env bash
# Fake gcloud: logs argv as JSON lines, fakes the few outputs the runbook parses.
python3 - "$@" <<'PY' >> "${RB_STUB_LOG}"
import json, sys
print(json.dumps(sys.argv[1:]))
PY
case "$*" in
  *"dataflow jobs run"*) echo "fake-job-$RANDOM" ;;
  *"dataflow jobs describe"*) echo "JOB_STATE_DONE" ;;
esac
exit 0
"""


def make_sandbox(root: Path) -> tuple[Path, Path]:
    stub_dir = root / "stubbin"
    stub_dir.mkdir(parents=True, exist_ok=True)
    g = stub_dir / "gcloud"
    g.write_text(_STUB)
    g.chmod(0o755)
    return stub_dir, root / "gcloud_calls.jsonl"


def run_runbook(out_dir: Path, sandbox_root: Path, env: dict[str, str] | None = None,
                unset: tuple[str, ...] = ("GCS_PREFIX",)) -> tuple[subprocess.CompletedProcess, list[list[str]]]:
    stub_dir, log = make_sandbox(sandbox_root)
    e = {k: v for k, v in os.environ.items() if k not in unset}
    for k in ("PROJECT_ID", "INSTANCE", "DATABASE", "REGION", "DATAFLOW_REGION", "DATAFLOW_SUBNETWORK",
              "DATAFLOW_DISABLE_PUBLIC_IPS"):
        e.pop(k, None)
    e.update({"PATH": f"{stub_dir}:{os.environ['PATH']}", "RB_STUB_LOG": str(log), "TMPDIR": str(sandbox_root)})
    e.update(env or {})
    p = subprocess.run(["bash", str(out_dir / "load_runbook.sh")], capture_output=True, text=True, env=e,
                       timeout=120, cwd=str(sandbox_root))
    calls = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
    return p, calls


def dataflow_params(calls: list[list[str]]) -> list[dict[str, str]]:
    """Parse --parameters=^SEP^k=v SEP k=v ... from captured `dataflow jobs run` calls."""
    out = []
    for argv in calls:
        if argv[:3] != ["dataflow", "jobs", "run"]:
            continue
        for a in argv:
            if a.startswith("--parameters="):
                raw = a[len("--parameters="):]
                if raw.startswith("^"):
                    sep_end = raw.index("^", 1)
                    sep = raw[1:sep_end]
                    raw = raw[sep_end + 1:]
                else:
                    sep = ","
                d = {}
                for kv in raw.split(sep):
                    k, _, v = kv.partition("=")
                    d[k] = v
                out.append(d)
    return out
