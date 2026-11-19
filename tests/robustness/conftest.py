"""Robustness suite plumbing: tier markers, opt-in gating, run-id, Neo4j + GCP session fixtures.

Tiers (see tests/ROBUSTNESS_TEST_PLAN.md):
  t0            offline (default)
  t1, t6        NEO4J_INTEGRATION=1 (podman Neo4j 4.4 on :7688, 5.x on :7687)
  t2, t3, t4    RB_GCP=1 (Spanner instance neo4j-robust-fn in driven-rig-474510-s8)
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
import secrets
import sys

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

from harness import findings as findings_mod  # noqa: E402

PROJECT_ID = os.environ.get("PROJECT_ID", "driven-rig-474510-s8")
INSTANCE = os.environ.get("INSTANCE", "neo4j-robust-fn")
GCS_ROOT = "gs://jicong/neo4j-robust"
REGION = "asia-southeast1"
SUBNET = "regions/asia-southeast1/subnetworks/sg-compute-subnet"
NEO4J_PW = os.environ.get("NEO4J_PASSWORD", "testpassword123")
NEO4J_URIS = {
    "v5": os.environ.get("NEO4J_V5_URI", "bolt://localhost:7687"),
    "v44": os.environ.get("NEO4J_V4_URI", "bolt://localhost:7688"),
}
CONTAINERS = {"v5": "neo4j-v5", "v44": "neo4j-v44"}

_TIER_ENV = {
    "t1": "NEO4J_INTEGRATION",
    "t6": "NEO4J_INTEGRATION",
    "t2": "RB_GCP",
    "t3": "RB_GCP",
    "t4": "RB_GCP",
}


def _run_id() -> str:
    rid = os.environ.get("RB_RUN_ID")
    if rid:
        return rid
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"rb-{ts}-{secrets.token_hex(2)}"


RUN_ID = _run_id()
REPORT_DIR = HERE / "reports" / RUN_ID


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--rb-keep", action="store_true", help="Do not tear down GCP resources at session end")
    parser.addoption("--rb-stop-neo4j", action="store_true", help="Stop Neo4j containers at session end")


def pytest_configure(config: pytest.Config) -> None:
    for t, desc in [
        ("t0", "offline unit/property/sandbox"),
        ("t1", "Neo4j integration"),
        ("t2", "DDL validity on empty Spanner DBs"),
        ("t3", "full E2E load"),
        ("t4", "verify mutation testing"),
        ("t6", "local fault injection"),
    ]:
        config.addinivalue_line("markers", f"{t}: {desc}")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    findings_mod.init(REPORT_DIR)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        for tier, env in _TIER_ENV.items():
            if item.get_closest_marker(tier) and os.environ.get(env) != "1":
                item.add_marker(pytest.mark.skip(reason=f"{tier} requires {env}=1"))


@pytest.fixture(scope="session")
def run_id() -> str:
    return RUN_ID


@pytest.fixture(scope="session")
def report_dir() -> Path:
    return REPORT_DIR


@pytest.fixture(scope="session")
def work_root() -> Path:
    p = Path("/tmp/rb") / RUN_ID
    p.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
def work_dir(work_root: Path, request: pytest.FixtureRequest) -> Path:
    name = request.node.name.replace("/", "_").replace("[", "_").replace("]", "")[:120]
    p = work_root / name
    if p.exists():
        import shutil

        shutil.rmtree(p)
    p.mkdir(parents=True)
    return p


# ----------------------------------------------------------------------------- Neo4j

@pytest.fixture(scope="session")
def neo4j_drivers():
    from neo4j import GraphDatabase

    from harness import neo4j_util

    drivers = {}
    for ver, uri in NEO4J_URIS.items():
        neo4j_util.ensure_container(CONTAINERS[ver], 7687 if ver == "v5" else 7688, ver, NEO4J_PW)
        drv = GraphDatabase.driver(uri, auth=("neo4j", NEO4J_PW))
        neo4j_util.wait_ready(drv)
        drivers[ver] = drv
    yield drivers
    for d in drivers.values():
        d.close()


@pytest.fixture(scope="session", params=["v5", "v44"])
def neo4j_any(request, neo4j_drivers):
    """Parametrized (version, driver) pair, for tests run against both Neo4j versions."""
    return request.param, neo4j_drivers[request.param]


@pytest.fixture(scope="session")
def neo4j_v44_only():
    """4.4 driver without touching the 5.x container (used by T2 while T6 pauses 5.x)."""
    from neo4j import GraphDatabase

    from harness import neo4j_util

    neo4j_util.ensure_container(CONTAINERS["v44"], 7688, "v44", NEO4J_PW)
    drv = GraphDatabase.driver(NEO4J_URIS["v44"], auth=("neo4j", NEO4J_PW))
    neo4j_util.wait_ready(drv)
    yield drv
    drv.close()


@pytest.fixture(scope="session")
def neo4j_v5(neo4j_drivers):
    return neo4j_drivers["v5"]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if session.config.getoption("--rb-stop-neo4j"):
        import subprocess

        for c in CONTAINERS.values():
            subprocess.run(["podman", "stop", c], check=False, capture_output=True)


# ----------------------------------------------------------------------------- GCP

@pytest.fixture(scope="session")
def gcp(request):
    """Session-scoped Spanner instance + GCS prefix with label/run-id scoped teardown (D4, D14)."""
    from harness import gcp_session

    sess = gcp_session.GcpSession(
        project=PROJECT_ID,
        instance=INSTANCE,
        run_id=RUN_ID,
        gcs_root=GCS_ROOT,
        region=REGION,
        subnet=SUBNET,
        report_dir=REPORT_DIR,
    )
    sess.preflight()
    sess.ensure_instance()
    yield sess
    if request.config.getoption("--rb-keep") or os.environ.get("RB_KEEP") == "1":
        sess.write_keep_notice()
    else:
        sess.teardown()
