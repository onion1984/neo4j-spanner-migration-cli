"""T4 re-run on R2 with a D16 workaround mapping (TIMESTAMP- and BYTES-PK tables removed from the
mapping passed to `verify`, because `verify` crashes on them: see H19 findings).

Reuses the T4 test functions from test_t3_t4_e2e.py with an `e2e` fixture that points at the loaded
rb_r2_01 database and a Neo4j holding the same R2 seed. Deltas vs. a fresh baseline are evaluated, so
baseline-only failures (e.g. synthetic-ID drift, widened PKs) do not affect mutation detection.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from neo4j import GraphDatabase
import pytest

from fixtures import graphs as g
from harness import runbook as rb
from harness.findings import record
import test_t3_t4_e2e as base

pytestmark = [pytest.mark.t4, pytest.mark.timeout(5400),
              pytest.mark.skipif(not Path("/tmp/rb/rb-20261119-015500-a1b2/t3_r2/verify_mapping_workaround.yaml").exists()
                                 or __import__("os").environ.get("RB_T4_WORKAROUND") != "1",
                                 reason="campaign-1 workaround only (RB_T4_WORKAROUND=1)")]

WORK = Path("/tmp/rb/rb-20261119-015500-a1b2/t3_r2")


@pytest.fixture(scope="module")
def e2e(gcp, work_root):
    drv = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", base.PW))
    g.seed_r2(drv)
    mapping = WORK / "verify_mapping_workaround.yaml"
    run = base.Run("r2", "bolt://localhost:7687", drv, "rb_r2_01", work_root / "t4_rerun_r2",
                   bundle=SimpleNamespace(mapping_path=mapping), load=rb.RunbookResult(0, Path("/dev/null"), 0.0, [], []))
    run.work.mkdir(parents=True, exist_ok=True)
    run.verify = base.run_verify(run, gcp, tag="base")
    record(None, "T4-rerun(setup)", "Observation",
           f"T4 re-run baseline verify rc={run.verify.get('rc')} with workaround mapping (PkTs, PkBytes and their edges removed); "
           f"baseline failures={sorted(base._verify_baseline_failures(run.verify))[:10]}",
           workaround="verify mapping without TIMESTAMP/BYTES PK tables (D16)")
    r3 = base.Run("r3", "", None, "rb_r3_01", work_root / "t3_r3", load=rb.RunbookResult(-2, Path("/dev/null"), 0.0, [], []))
    yield {"r2": run, "r3": r3}, {}
    drv.close()


test_H01_string_mutation_detected = base.test_H01_string_mutation_detected
test_H02_H03_count_mutations_detected = base.test_H02_H03_count_mutations_detected
test_H04_timestamp_mutation_detected = base.test_H04_timestamp_mutation_detected
test_H05_float_ulp_mutation_detected = base.test_H05_float_ulp_mutation_detected
test_H08_wrong_graph = base.test_H08_wrong_graph
test_H09_custom_queries_file = base.test_H09_custom_queries_file
