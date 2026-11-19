# Robustness suite for `neo4j-spanner-export`

Implements [`../ROBUSTNESS_TEST_PLAN.md`](../ROBUSTNESS_TEST_PLAN.md). Results of the first campaign are in
[`reports/rb-20261119-015500-a1b2/`](reports/rb-20261119-015500-a1b2/) (`summary.md`, `defects.md`).

## Layout

| Path | Purpose |
| :--- | :--- |
| `conftest.py` | Tier markers + opt-in gating, run-id, Neo4j fixtures, session-scoped GCP fixture (instance + GCS prefix, label/run-id scoped teardown) |
| `harness/findings.py` | `check()` asserts the *correct* behaviour and records Confirmed/Refuted per hypothesis into `reports/<run-id>/findings.jsonl` |
| `harness/oracle.py` | Independent oracle (golden comparator + converter); never imports the tool |
| `harness/spanner_ddl.py` | T2: apply generated DDL to empty Spanner DBs with per-statement error capture |
| `harness/runbook.py` | T3: run `load_runbook.sh` against the session resources |
| `harness/sandbox.py` | Stub-`gcloud` sandbox for runbook injection / parameter tests |
| `harness/gcp_session.py` | Instance/prefix lifecycle; refuses to adopt or delete anything not labelled with this run-id |
| `harness/defect_log.py`, `harness/final_pass.py` | Build `summary.md` / `defects.md` |
| `fixtures/graphs.py`, `fixtures/golden_r2.py` | Graph seeds (G0–G6, R4) and hand-written golden expectations |
| `test_t0_*.py` | Offline unit, property-based, sandbox and static-review tests |
| `test_t1_*.py` | Neo4j 4.4 + 5.x integration (discover/export/CLI) |
| `test_t2_ddl.py` | Generated DDL on empty Spanner DBs |
| `test_t3_t4_e2e.py` | Full loads R1–R4 (+ `--emit-unescape`, public-IP negative) and `verify` mutation tests |
| `test_t4_rerun_r2.py` | T4 on R2 with the D16 workaround mapping (verify crashes on TIMESTAMP/BYTES PKs) |
| `test_t6_faults.py` | Local fault injection |

## Running

```bash
# offline (default, free)
.venv/bin/pytest tests/robustness -m t0 -p no:cacheprovider

# Neo4j 4.4 (:7688) + 5.x (:7687) via podman (started automatically if absent)
NEO4J_INTEGRATION=1 .venv/bin/pytest tests/robustness -m "t1 or t6" -p no:cacheprovider

# GCP tiers (project driven-rig-474510-s8). Instance neo4j-robust-fn is created at session start and
# deleted at session end unless --rb-keep. Use one RB_RUN_ID for a whole campaign so findings accumulate.
RB_RUN_ID=rb-YYYYMMDD-HHMMSS-abcd RB_GCP=1 NEO4J_INTEGRATION=1 \
  .venv/bin/pytest tests/robustness -m "t2 or t3 or t4" -p no:cacheprovider --timeout=10800

# report
(cd tests/robustness && ../../.venv/bin/python -m harness.final_pass reports/$RB_RUN_ID)
```

Useful switches: `RB_T3_RUNS=r2,r1u` (subset of E2E runs), `RB_T3_CONTAINER_SUFFIX=N` (parallel sessions use
separate Neo4j containers/ports), `RB_T2_CASES=...`, `RB_T2_WORKERS=2`, `RB_R3_DELIM=';'`,
`RB_MAPPING_SOURCE=/tmp/rb/<previous-run-id>` (export/DDL from a previous campaign's mappings when discovery is
broken), `RB_NO_INPUTMAP_WORKAROUND=1` (pass partial input mappings unchanged).

Campaigns so far: `rb-20261119-015500-a1b2` (baseline, 38 defects), `rb-20261119-044800-c2d3` (re-test 1: 31 fixed,
7 new) and `rb-20261119-083000-c3e4` (re-test 2: 36/38 and 10/12 fixed, 0 new; see
`reports/rb-20261119-083000-c3e4/retest.md`). Generate the comparison with
`defect_log.build_retest(Path('reports/<old>'), Path('reports/<new>'))`.

> [!NOTE]
> A 100-PU Spanner instance allows at most 10 databases; T2 runs 6 DDL cases in parallel and each T3 run uses
> its own database, so do not start T2 and a full T3 session at the same time.

Tests assert the expected-correct behaviour, so **a failing test usually means a confirmed defect**; see
`reports/<run-id>/defects.md` for the classification.
