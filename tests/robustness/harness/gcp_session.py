"""Per-session GCP resources: Spanner instance + GCS prefix, with label/run-id scoped teardown."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

_PREFIX_RE = re.compile(r"^gs://jicong/neo4j-robust/rb-\d{8}-\d{6}-[0-9a-f]{4}/$")


def _gc(args: list[str], check: bool = True, timeout: float = 900) -> subprocess.CompletedProcess:
    p = subprocess.run(["gcloud", *args, "--quiet"], capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"gcloud {' '.join(args)} failed: {p.stderr[-2000:]}")
    return p


class GcpSession:
    def __init__(self, project, instance, run_id, gcs_root, region, subnet, report_dir: Path):
        self.project = project
        self.instance = instance
        self.run_id = run_id
        self.region = region
        self.subnet = subnet
        self.gcs_prefix = f"{gcs_root}/{run_id}/"
        self.report_dir = report_dir
        self.info: dict = {"run_id": run_id, "project": project, "instance": instance, "gcs_prefix": self.gcs_prefix}
        self._client = None

    # ---------------------------------------------------------------- setup
    def preflight(self) -> None:
        proj = _gc(["config", "get-value", "project"]).stdout.strip()
        pga = _gc([
            "compute", "networks", "subnets", "describe", "sg-compute-subnet",
            f"--region={self.region}", f"--project={self.project}", "--format=value(privateIpGoogleAccess)",
        ]).stdout.strip()
        sa = "379924935547-compute@developer.gserviceaccount.com"
        roles = _gc([
            "projects", "get-iam-policy", self.project, "--flatten=bindings[].members",
            f"--filter=bindings.members:serviceAccount:{sa}", "--format=value(bindings.role)",
        ]).stdout.split()
        self.info.update({"gcloud_project": proj, "subnet_private_google_access": pga, "dataflow_sa": sa,
                          "dataflow_sa_roles": roles})
        self._write()
        if pga != "True":
            raise RuntimeError("sg-compute-subnet must have Private Google Access")

    def _labels(self) -> dict | None:
        p = _gc(["spanner", "instances", "describe", self.instance, f"--project={self.project}",
                 "--format=json(labels)"], check=False)
        if p.returncode != 0:
            return None
        return (json.loads(p.stdout or "{}") or {}).get("labels") or {}

    def ensure_instance(self) -> None:
        labels = self._labels()
        if labels is None:
            _gc(["spanner", "instances", "create", self.instance, f"--project={self.project}",
                 "--config=regional-asia-southeast1", "--edition=ENTERPRISE", "--processing-units=100",
                 "--description=neo4j robustness test"])
            _gc(["spanner", "instances", "update", self.instance, f"--project={self.project}",
                 f"--update-labels=purpose=neo4j-robustness-test,rb-run-id={self.run_id}"])
            self.info["instance_created"] = True
        elif labels.get("purpose") == "neo4j-robustness-test" and labels.get("rb-run-id") == self.run_id:
            self.info["instance_created"] = "reused-same-run-id"
        else:
            raise RuntimeError(
                f"Instance {self.instance} exists but is not owned by run {self.run_id} (labels={labels}); refusing to adopt."
            )
        self._write()

    # ---------------------------------------------------------------- spanner client
    @property
    def spanner_instance(self):
        if self._client is None:
            from google.cloud import spanner

            self._client = spanner.Client(project=self.project)
        return self._client.instance(self.instance)

    def database(self, db_id: str):
        return self.spanner_instance.database(db_id)

    def prefix(self, name: str) -> str:
        return f"{self.gcs_prefix}{name}"

    # ---------------------------------------------------------------- teardown
    def write_keep_notice(self) -> None:
        self.info["teardown"] = {
            "skipped": "--rb-keep",
            "manual": [
                f"gcloud spanner instances delete {self.instance} --project={self.project}",
                f"gcloud storage rm --recursive {self.gcs_prefix}",
            ],
        }
        self._write()

    def teardown(self) -> None:
        res: dict = {}
        labels = self._labels()
        if labels and labels.get("purpose") == "neo4j-robustness-test" and labels.get("rb-run-id") == self.run_id:
            p = _gc(["spanner", "instances", "delete", self.instance, f"--project={self.project}"], check=False)
            res["instance"] = "deleted" if p.returncode == 0 else f"ERROR {p.stderr[-500:]}"
        else:
            res["instance"] = f"not deleted (labels={labels})"
        if _PREFIX_RE.match(self.gcs_prefix):
            p = _gc(["storage", "rm", "--recursive", self.gcs_prefix], check=False)
            res["gcs"] = "deleted" if p.returncode == 0 else f"rc={p.returncode} {p.stderr[-300:]}"
            left = _gc(["storage", "ls", self.gcs_prefix], check=False)
            res["gcs_leftovers"] = left.stdout.strip().splitlines() if left.returncode == 0 else []
        else:
            res["gcs"] = f"REFUSED: prefix {self.gcs_prefix} failed safety regex"
        self.info["teardown"] = res
        self._write()
        (self.report_dir / "teardown.json").write_text(json.dumps(res, indent=2) + "\n")

    def _write(self) -> None:
        (self.report_dir / "session.json").write_text(json.dumps(self.info, indent=2, default=str) + "\n")
