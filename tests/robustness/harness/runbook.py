"""T3 helper: run a generated load_runbook.sh against the session GCP resources."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import time


@dataclass
class RunbookResult:
    rc: int
    log_path: Path
    elapsed_s: float
    job_ids: list[str]
    stages: list[str]

    @property
    def log(self) -> str:
        return self.log_path.read_text(errors="replace")


def run(out_dir: Path, gcp, db_id: str, gcs_prefix: str, disable_public_ips: bool = True,
        extra_env: dict[str, str] | None = None, timeout: float = 7200) -> RunbookResult:
    env = dict(os.environ)
    env.update({
        "PROJECT_ID": gcp.project,
        "INSTANCE": gcp.instance,
        "DATABASE": db_id,
        "REGION": gcp.region,
        "DATAFLOW_REGION": gcp.region,
        "DATAFLOW_SUBNETWORK": gcp.subnet,
        "DATAFLOW_DISABLE_PUBLIC_IPS": "true" if disable_public_ips else "false",
        "GCS_PREFIX": gcs_prefix.rstrip("/"),
    })
    env.update(extra_env or {})
    log = out_dir.parent / f"runbook_{db_id}.log"
    t0 = time.time()
    with log.open("w") as fh:
        try:
            p = subprocess.run(["bash", str(out_dir / "load_runbook.sh")], stdout=fh, stderr=subprocess.STDOUT,
                               env=env, timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = -999
    text = log.read_text(errors="replace")
    jobs = re.findall(r"Dataflow Job ID: (\S+)", text)
    stages = re.findall(r"^=== (.+) ===$", text, flags=re.M)
    return RunbookResult(rc, log, time.time() - t0, jobs, stages)


def cancel_jobs(gcp, job_ids: list[str]) -> None:
    for j in job_ids:
        subprocess.run(["gcloud", "dataflow", "jobs", "cancel", j, f"--region={gcp.region}", f"--project={gcp.project}", "--quiet"],
                       capture_output=True)


def job_error(gcp, job_id: str) -> str:
    p = subprocess.run(["gcloud", "logging", "read",
                        f'resource.type="dataflow_step" AND resource.labels.job_id="{job_id}" AND severity>=ERROR',
                        f"--project={gcp.project}", "--limit=3", "--format=value(textPayload,jsonPayload.message)"],
                       capture_output=True, text=True, timeout=120)
    return p.stdout[:3000]
