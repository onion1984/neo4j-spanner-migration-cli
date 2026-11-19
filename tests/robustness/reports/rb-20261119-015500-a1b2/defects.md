# Defect log

Run: `rb-20261119-015500-a1b2` · generated from `findings.jsonl` (latest record per test).

| DEF | Hypothesis | Severity | Title | Tests |
| :--- | :--- | :--- | :--- | :--- |
| DEF-001 | H01 | P0 | verify cannot catch coercion bugs (shares coerce_value()) | H-01(golden-vs-verify) |
| DEF-002 | H02 | P0 | DateTime ns truncated to µs; verify compares only to ms | D-14(T0), D-14(T3:VDateTime), H-04 |
| DEF-003 | H03 | P0 | INT64+FLOAT64 widening loses precision > 2^53; verify isclose hides it | D-05, D-05(T3:TConf), H-05 |
| DEF-004 | H04 | P0 | Type overrides not validated (truncation / silent false / invalid DDL types) | A-08, A-08(T2), D-10, D-10(T1), D-11 |
| DEF-005 | H05 | P0 | pk_overrides not checked for uniqueness or legal PK type | B-09, B-10, B-10(T2) |
| DEF-006 | H08 | P0 | Same property name, different types across node labels breaks graph DDL | F-05 |
| DEF-007 | H06 | P1 | Mixed-type unique keys collapse to duplicate STRING PKs | B-11 |
| DEF-008 | H07 | P1 | NaN/Infinity inside lists -> invalid JSON | D-08, D-08(T3)/G-04 |
| DEF-009 | H09 | P1 | Conflicting ARRAY/JSON types on a shared edge label emit an invalid CAST (CAST(NULL AS STRING(MAX)) and INT->STRING are accepted) | F-07 |
| DEF-010 | H10 | P1 | Secondary labels not queryable as GQL labels | F-09 |
| DEF-011 | H11 | P1 | FK/index name truncation collisions | C-07, C-07(T0) |
| DEF-012 | H15 | P1 | --gcs-prefix / --graph-name injection | F-08, L-03, L-04 |
| DEF-013 | H16 | P1 | Stale shards loaded (local dir / GCS prefix) | G-09(H16-GCS), K-05, K-10 |
| DEF-014 | H18 | P1 | --sample-size type drift crashes export with partial bundle | A-06 |
| DEF-015 | H19 | P1 | verify false missing_in_neo4j for widened/TIMESTAMP/BYTES PKs | H-06 |
| DEF-016 | H21 | P1 | Runbook not idempotent / no resume | G-09(H21) |
| DEF-017 | H22 | P1 | Out-of-range dates crash / corrupt export | D-15 |
| DEF-018 | NEW-DIGITNAME | P1 | Original property/label names starting with a digit break CREATE PROPERTY GRAPH | C-05(T2)/F-01[G3] |
| DEF-019 | NEW-HANG | P1 | A single rejected row makes the Dataflow load hang (no invalidOutputPath); oversized values not detected | D-08(T3:r4), G-01[r2]/E-07(T3) |
| DEF-020 | NEW-NOEDGE | P1 | load_runbook.sh fails for graphs without relationships (missing edges/ directory) | G-10(nodes-only) |
| DEF-021 | NEW-TAB | P1 | Tab delimiter is accepted by export but breaks the Dataflow load | E-06(T3:r3) |
| DEF-022 | NEW-UNESCAPE | P1 | --emit-unescape generates invalid SQL (03_unescape.sql) and aborts the load | E-03(unescape) |
| DEF-023 | H12 | P2 | dst_ prefix exceeds 128 chars | C-08, C-08(T0) |
| DEF-024 | H13 | P2 | Backtick escaping in graph DDL | C-09 |
| DEF-025 | H14 | P2 | Delimiter '~' breaks Dataflow parameter separator | G-06 |
| DEF-026 | H17 | P2 | 0-row table -> manifest glob matches nothing | K-03 |
| DEF-027 | H20 | P2 | verify sampling limited to first 50k rows | H-07 |
| DEF-028 | H23 | P2 | Spanner column limit not detected | F-04 |
| DEF-029 | H25 | P2 | Empty DB -> invalid NODE TABLES () | B-14[v44], B-14[v5] |
| DEF-030 | H26 | P2 | Unknown/missing YAML keys -> raw TypeError | A-04[missing_field], A-04[unknown_key] |
| DEF-031 | NEW-DET | P2 | schema_mapping.yaml not byte-identical across Neo4j versions | F-11b |
| DEF-032 | NEW-EMPTY | P2 | An empty schema_mapping.yaml exports 0 rows with exit code 0 | A-04[empty_file] |
| DEF-033 | NEW-EMPTYBYTES | P2 | Empty BYTES values become NULL after load | D-19(T3:VBytes) |
| DEF-034 | NEW-JOBNAME | P2 | Dataflow job names collide when two loads start in the same second | G-11(job-name) |
| DEF-035 | NEW-LABELCLASH | P2 | Node label and relationship type with the same name produce conflicting LABEL definitions | C-11 |
| DEF-036 | NEW-MONO | P2 | Monotonic-PK hotspot warning depends on Neo4j scan order | B-15 |
| DEF-037 | NEW-SIZE | P2 | Values above Spanner limits (STRING 2,621,440 chars / 10 MiB) are not detected before load | E-07 |
| DEF-038 | NEW-UX | P2 | CLI surfaces operational/validation errors as raw Python tracebacks | A-02, A-03, A-05, A-10, H-09 |

### DEF-001 — verify cannot catch coercion bugs (shares coerce_value())

- **Hypothesis:** H01 · **Severity:** P0 · **Status:** Confirmed
- **Tests:** H-01(golden-vs-verify)
- **Workaround used / available:** Validate migrated values with an independent check (e.g. harness/oracle.py golden comparison), not only `verify`.
- **Evidence:**

  `H-01(golden-vs-verify)`

  ```text
  Same loaded DB rb_r2_01: independent golden oracle found 4 value diffs [('VBytes', "('empty',)", 'by_val'), ('VDateTime', "('utc_ns',)", 'dt_val'), ('VDateTime', "('max',)", 'dt_val'), ('TConf', "('r3',)", 'c_if')]; verify (sample-rows >= table size) flagged sample mismatches only in ['PkNone', 'PkNone__REL_C__PkNone', 'PkWide', 'VBytes']. Missed by verify: [('VDateTime', "('utc_ns',)", "('ts', 1773568800, 123456789)", "('ts', 1773568800, 123456000)"), ('VDateTime', "('max',)", "('ts', 253402300799, 999999999)", "('ts', 253402300799, 999999000)"), ('TConf', "('r3',)", '9007199254740993', '9007199254740992.0')] -> verify normalizes both sides through the exporter's coerce_value (ns->us truncation) and compares FLOAT64 with isclose, so lossy conversions pass. (Direct post-load value edits ARE detected: H-01 string mutation.)
  ```

### DEF-002 — DateTime ns truncated to µs; verify compares only to ms

- **Hypothesis:** H02 · **Severity:** P0 · **Status:** Confirmed
- **Tests:** D-14(T0), D-14(T3:VDateTime), H-04
- **Workaround used / available:** None at input level; keep sub-µs precision out of scope or store as STRING via `override: STRING(MAX)`.
- **Evidence:**

  `D-14(T0)`

  ```text
  Neo4j DateTime ...00.123456789Z -> CSV '2026-03-15T10:00:00.123456Z'
  ```

  `D-14(T3:VDateTime)`

  ```text
  [{"table": "VDateTime", "key": "('utc_ns',)", "column": "dt_val", "expected": "('ts', 1773568800, 123456789)", "actual": "('ts', 1773568800, 123456000)"}, {"table": "VDateTime", "key": "('max',)", "column": "dt_val", "expected": "('ts', 253402300799, 999999999)", "actual": "('ts', 253402300799, 999999000)"}]
  ```

  `H-04`

  ```text
  detected per delta: {'1us': (1, False), '1ms': (1, True)}
  ```

### DEF-003 — INT64+FLOAT64 widening loses precision > 2^53; verify isclose hides it

- **Hypothesis:** H03 · **Severity:** P0 · **Status:** Confirmed
- **Tests:** D-05, D-05(T3:TConf), H-05
- **Workaround used / available:** Set `override: STRING(MAX)` on mixed INT/FLOAT properties holding large integers.
- **Evidence:**

  `D-05`

  ```text
  INT64+FLOAT64 -> FLOAT64 (conflict=True); coerce(9007199254740993) -> '9007199254740992.0' (int value 9007199254740992); no warning beyond is_conflict flag
  ```

  `D-05(T3:TConf)`

  ```text
  [{"table": "TConf", "key": "('r3',)", "column": "c_if", "expected": "9007199254740993", "actual": "9007199254740992.0"}]
  ```

  `H-05`

  ```text
  1-ULP FLOAT64 change detected=False; INT>2^53 in FLOAT64 col changed by 2 detected=False
  ```

### DEF-004 — Type overrides not validated (truncation / silent false / invalid DDL types)

- **Hypothesis:** H04 · **Severity:** P0 · **Status:** Confirmed
- **Tests:** A-08, A-08(T2), D-10, D-10(T1), D-11
- **Workaround used / available:** Only use overrides that are lossless for the observed data; validate manually.
- **Evidence:**

  `D-10`

  ```text
  override INT64: coerce(3.7) -> '3' (silent truncation); coerce('abc') -> ValueError: invalid literal for int() with base 10: 'abc' (uncaught at export)
  ```

  `D-11`

  ```text
  BOOL coercion results: {'no': 'false', 'N': 'false', '0': 'false', 'maybe': 'false', 'TRUE': 'true', 'yes': 'true'}; unknown strings silently -> false: ['maybe', 'N']
  ```

  `A-08`

  ```text
  override VARCHAR accepted; DDL contains: ['  age VARCHAR']
  ```

  `D-10(T1)`

  ```text
  override amt: INT64 on [3.7, 10.2] -> CSV ['a,3', 'b,10']
  ```

### DEF-005 — pk_overrides not checked for uniqueness or legal PK type

- **Hypothesis:** H05 · **Severity:** P0 · **Status:** Confirmed
- **Tests:** B-09, B-10, B-10(T2)
- **Workaround used / available:** Manually check uniqueness (`MATCH (n:L) WITH n.k AS k, count(*) AS c WHERE c>1 RETURN k`) and only use scalar PK columns.
- **Evidence:**

  `B-09`

  ```text
  pk_overrides Ord:[code] accepted; CSV contains duplicate PK values ['X'] -> Dataflow load would hit ALREADY_EXISTS
  ```

  `B-10`

  ```text
  {'tags': ('accepted', 'ARRAY<STRING(MAX)>', ['  tags__json JSON NOT NULL,', ') PRIMARY KEY (tags__json);']), 'loc': ('accepted', 'JSON', ['  loc JSON NOT NULL,', ') PRIMARY KEY (loc);'])}
  ```

  `B-10(T2)`

  ```text
  {'B10_pk_JSON': '01_create_tables.sql: stmt#0 ERROR 400 Column Jpk.jk has type JSON, but is part of the primary key. 3: Column Jpk.jk has type JSON, but is part of the primary key. :: CREATE TABLE Jpk (\n  jk JSON NOT NULL,\n  other INT64\n) PRIMARY KEY (jk)\n05_property_graph.sql: stmt#0 ERROR 400 Error analyzing the definition of graph `RbGraph`: Table not found: Jpk [at 3:5]\\n    Jpk\\n    ^ 3: Error analyzing the definition of graph `RbGraph`: Table not found: Jpk [at 3:5]\\n    Jpk\\n    ^ :: CREATE OR REPLACE PROPERTY GRAPH RbGraph\nNODE TABLES (\n  Jpk\n    KEY (jk)\n    LABEL `Jpk`\n    PROPERTIES (jk AS `jk`, other AS `other`)\n)', 'B10_pk_ARRAY': '01_create_tables.sql: stmt#0 ERROR 400 Column Jpk.jk__json has type JSON, but is part of the primary key. 3: Column Jpk.jk__json has type JSON, but is part of the primary key. :: CREATE TABLE Jpk (\n  jk__json JSON NOT NULL,\n  other INT64\n) PRIMARY KEY (jk__json)\n02_arrays_add.sql: stmt#0 ERROR 404 Table not found: Jpk 5: Table not found: Jpk :: ALTER TABLE Jpk ADD COLUMN jk ARRAY<STRING(MAX)>\n02_arrays_drop.sql: stmt#0 ERROR 404 Table not found: Jpk 5: Table not found: Jpk :: ALTER TABLE Jpk DROP COLUMN jk__json\n05_property_graph.sql: stmt#0 ERROR 400 Error analyzing the definition of graph `RbGraph`: Table not found: Jpk [at 3:5]\\n    Jpk\\n    ^ 3: Error analyzing the definition of graph `RbGraph`: Table not found: Jpk [at 3:5]\\n    Jpk\\n    ^ :: CREATE OR REPLACE PROPERTY GRAPH RbGraph\nNODE TABLES (\n  Jpk\n    KEY (jk)\n    LABEL `Jpk`\n    PROPERTIES (jk AS `jk`, other AS `other`)\n)'}
  ```

### DEF-006 — Same property name, different types across node labels breaks graph DDL

- **Hypothesis:** H08 · **Severity:** P0 · **Status:** Confirmed
- **Tests:** F-05
- **Workaround used / available:** Use `column_renames` so same-named properties with different types get distinct names.
- **Evidence:**

  `F-05`

  ```text
  05_property_graph.sql: stmt#0 ERROR 400 Error analyzing the definition of graph `RbGraph`: The property declaration of \'code\' has type conflicts. There is an existing declaration of type STRING. There is a conflicting one of type INT64 [at 13:9]\n        code AS code)\n        ^ 3: Error analyzing the definition of graph `RbGraph`: The property declaration of \'code\' has type conflicts. There is an existing declaration of type STRING. There is a conflicting one of type INT64 [at 13:9]\n        code AS code)\n        ^ :: CREATE OR REPLACE PROPERTY GRAPH RbGraph
  NODE TABLES (
    Person
      KEY (pid)
      LABEL `Person`
      PROPERTIES (pid AS `pid`, code AS `code`),
    Company
      KEY (cid)
      LABEL `Company`
      PROPERTIES (cid AS `cid`, code AS `code`)
  )
  EDGE TABLES (
    Person__WORKS_AT__Company
      KEY (pid, dst_cid)
      SOURCE KEY (pid) REFERENCES Person (pid)
      DESTINATION KEY (dst_cid) REFERENCES Company (cid)
      LABEL `WORKS_AT`
      NO PROPERTIES
  )
  ```

### DEF-007 — Mixed-type unique keys collapse to duplicate STRING PKs

- **Hypothesis:** H06 · **Severity:** P1 · **Status:** Confirmed
- **Tests:** B-11
- **Workaround used / available:** Normalise key types in Neo4j before export, or use the synthetic `_neo4j_id` PK.
- **Evidence:**

  `B-11`

  ```text
  PK type STRING(MAX); CSV keys ['1', '1'] (two distinct Neo4j keys -> one Spanner key)
  ```

### DEF-008 — NaN/Infinity inside lists -> invalid JSON

- **Hypothesis:** H07 · **Severity:** P1 · **Status:** Confirmed
- **Tests:** D-08, D-08(T3)/G-04
- **Workaround used / available:** Replace NaN/Infinity inside lists in Neo4j before export.
- **Evidence:**

  `D-08`

  ```text
  non-RFC8259 JSON emitted: {'[1.5, nan]': ('INVALID', '[1.5,NaN]', 'non-RFC8259 JSON constant NaN'), '[inf]': ('INVALID', '[Infinity]', 'non-RFC8259 JSON constant Infinity'), "[1, 'a', nan]": ('INVALID', '[1,"a",NaN]', 'non-RFC8259 JSON constant NaN')}
  ```

  `D-08(T3)/G-04`

  ```text
  R4 ([NaN], [Infinity] list values): rc=1; stages reached=['1. Create Spanner database with Stage 01 DDL', '2. Upload CSV shards and manifests to GCS', '3. Run Dataflow job 1 (Nodes)']; log tail:
  ING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE_RUNNING
  Job 2026-11-18_18_52_50-15698955132928148999 state: JOB_STATE
  ```

### DEF-009 — Conflicting ARRAY/JSON types on a shared edge label emit an invalid CAST (CAST(NULL AS STRING(MAX)) and INT->STRING are accepted)

- **Hypothesis:** H09 · **Severity:** P1 · **Status:** Confirmed
- **Tests:** F-07
- **Workaround used / available:** Use `column_renames`/`override` so a shared rel-type property has one type across triplets, and avoid STRING props missing from some triplets.
- **Evidence:**

  `F-07`

  ```text
  ARRAY vs INT64: 05_property_graph.sql: stmt#0 ERROR 400 Error analyzing the definition of graph `RbGraph`: Invalid cast from ARRAY<INT64> to STRING [at 19:14]\n        CAST(val AS STRING(MAX)) AS val),\n             ^ 3: Error analyzing the definition of graph `RbGraph`: Invalid cast from ARRAY<INT64> to STRING [at 19:14]\n        CAST(val AS STRING(MAX)) AS val),\n             ^ :: CREATE OR REPLACE PROPERTY GRAPH RbGraph
  NODE TABLES (
    Person
      KEY (pid)
      LABEL `Person`
      PROPERTIES (pid AS `pid`),
    Company
      KEY (cid)
      LABEL `Company`
      PROPERTIES (cid AS `cid`)
  )
  EDGE TABLES (
    Person__TAGS__Person
      KEY (pid, dst_pid)
      SOURCE KEY (pid) REFERENCES Person (pid)
      DESTINATION KEY (dst_pid) REFERENCES Person (pid)
      LABEL `TAGS`
      PROPERTIES (CAST(val AS STRING(MAX)) AS `val`),
    Person__TAGS__Company
      KEY (pid, dst_cid)
      SOURCE KEY (pid) REFERENCES Person (pid)
      DESTINATION KEY (dst_cid) REFERENCES Company (cid)
      LABEL `TAGS`
      
  INT64 vs STRING: all statements accepted
  ```

### DEF-010 — Secondary labels not queryable as GQL labels

- **Hypothesis:** H10 · **Severity:** P1 · **Status:** Confirmed
- **Tests:** F-09
- **Workaround used / available:** Query `WHERE 'Label' IN UNNEST(n.secondary_labels)` instead of `MATCH (n:Label)`.
- **Evidence:**

  `F-09`

  ```text
  Cypher MATCH (n:Employee) -> 200; GQL MATCH (n:Employee) -> ERROR 400 Failed to find element label [Employee] in PropertyGraph: RbR3 [at 1:21]\nGRAPH RbR3 MATCH (n:Employee) RETURN COUNT(*) AS c\n                    ^, request_id = 1.399258424408237936.1.21.44.1 [lo; workaround via secondary_labels -> 200
  ```

### DEF-011 — FK/index name truncation collisions

- **Hypothesis:** H11 · **Severity:** P1 · **Status:** Confirmed
- **Tests:** C-07, C-07(T0)
- **Workaround used / available:** Use `table_renames` to shorten long edge table names (<= 120 chars).
- **Evidence:**

  `C-07(T0)`

  ```text
  duplicate FK/index names for two valid 128-char edge tables: ['fk_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA__RELX__BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB', 'idx_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA__RELX__BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB']
  ```

  `C-07`

  ```text
  04_constraints_indexes.sql: stmt#2 ERROR 400 Duplicate name in schema: fk_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA__RELX__BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB. 9: Duplicate name in schema: fk_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA__RELX__BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB. :: ALTER TABLE AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA__RELX__BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB2 ADD CONSTRAINT fk_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA__RELX__BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB FOREIGN KEY (dst_id) REFERENCES BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB2 (id)
  04_constraints_indexes.sql: stmt#3 ERROR 400 Duplicate name in schema: idx_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA__RELX__BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB. 9: Duplicate name in schema: idx_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA__RELX__BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB. :: CREATE INDEX idx_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA__RELX__BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB ON AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA__RELX__BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB2 (dst_id, id)
  ```

### DEF-012 — --gcs-prefix / --graph-name injection

- **Hypothesis:** H15 · **Severity:** P1 · **Status:** Confirmed
- **Tests:** F-08, L-03, L-04
- **Workaround used / available:** Only pass trusted, plain `gs://bucket/path` prefixes and simple graph names; always export GCS_PREFIX before running the runbook.
- **Evidence:**

  `L-03`

  ```text
  --gcs-prefix 'gs://b/$(touch …)' accepted by export; running load_runbook.sh executed it: marker exists=True; runbook line: ['GCS_PREFIX="${GCS_PREFIX:-gs://b/$(touch /tmp/pytest-of-jicong/pytest-10/test_L03_gcs_prefix_shell_inje0/sb/rb_pwned)}"']
  ```

  `L-04`

  ```text
  --graph-name accepted; 05_property_graph.sql head: 'CREATE OR REPLACE PROPERTY GRAPH G; DROP TABLE Person'
  ```

  `F-08`

  ```text
  --graph-name accepted by tool; Spanner: my-graph -> 05_property_graph.sql: stmt#0 ERROR 400 Error analyzing the definition of graph `my`: Syntax error: Expected \".\" or keyword NODE but got \"-\" [at 1:36]\nCREATE OR REPLACE PROPERTY GRAPH my-graph\n                                   ^ 3: Error analyzing the definition of graph `my`: Syntax error: Expected \".\" or keyword NODE but got \"-\" [at 1:36]\nCREATE OR REPLACE PROPERTY GRAPH my-graph\n  ; Select -> setup: stmt#- ERROR 400 Error parsing Spanner DDL statement: CREATE OR REPLACE PROPERTY GRAPH Select\nNODE TABLES (\n  Gn\n    KEY (gid)\n    LABEL `Gn`\n    PROPERTIES (gid AS `gid`)\n) : Syntax error on line 1, column 34: Encountered \'Select\' while parsing: identifier [locale: "en-US"
  message: "Error parsing Spanner DDL statement: CREATE OR REPLACE PROPERTY GRAPH Select\nNODE TABLES (\n  Gn\n 
  ```

### DEF-013 — Stale shards loaded (local dir / GCS prefix)

- **Hypothesis:** H16 · **Severity:** P1 · **Status:** Confirmed
- **Tests:** G-09(H16-GCS), K-05, K-10
- **Workaround used / available:** Always export into a fresh --output-dir and a fresh GCS prefix.
- **Evidence:**

  `K-05`

  ```text
  second export reported 2 rows but 6 shards / 6 rows match the manifest glob (['St_part_00000.csv', 'St_part_00001.csv', 'St_part_00002.csv', 'St_part_00003.csv', 'St_part_00004.csv', 'St_part_00005.csv'])
  ```

  `K-10`

  ```text
  fresh-dir kill leaves complete-looking bundle=False; re-run kill: old runbook/manifests still present=True, rows on disk=54000/300000 (complete first run had 300000), truncated shards=[]
  ```

  `G-09(H16-GCS)`

  ```text
  upload uses `gcloud storage cp --recursive` without clearing the prefix (True) and the manifest uses a wildcard `<table>_part_*.csv` (True); stale shards from an earlier, larger export under the same GCS_PREFIX are loaded too (combined with K-05 local evidence).
  ```

### DEF-014 — --sample-size type drift crashes export with partial bundle

- **Hypothesis:** H18 · **Severity:** P1 · **Status:** Confirmed
- **Tests:** A-06
- **Workaround used / available:** Do not use --sample-size for the final discovery.
- **Evidence:**

  `A-06`

  ```text
  export raised ValueError: invalid literal for int() with base 10: 'not-a-number'; partial files left: ['Dr_part_00000.csv']
  ```

### DEF-015 — verify false missing_in_neo4j for widened/TIMESTAMP/BYTES PKs

- **Hypothesis:** H19 · **Severity:** P1 · **Status:** Confirmed
- **Tests:** H-06
- **Workaround used / available:** Interpret verify sample failures on such tables manually.
- **Evidence:**

  `H-06`

  ```text
  Clean R2 DB (all values loaded) -> `verify` exits 1 WITHOUT writing a report: (1) TIMESTAMP PK (PkTs.ts): Spanner DatetimeWithNanoseconds is passed as a Neo4j query parameter -> ValueError: Values of type DatetimeWithNanoseconds are not supported (crash). (2) BYTES PK (PkBytes.bk): lookup misses -> missing_in_neo4j, then writing the report fails with TypeError: Object of type bytes is not JSON serializable (crash). (3) Widened STRING PK (PkWide.wk '1','2' from Neo4j ints): false missing_in_neo4j. (4) Synthetic-PK tables: verify maps Spanner keys back via bit-reversed internal id(), so any Neo4j re-import/compaction makes every row 'missing_in_neo4j'.
  ```

### DEF-016 — Runbook not idempotent / no resume

- **Hypothesis:** H21 · **Severity:** P1 · **Status:** Confirmed
- **Tests:** G-09(H21)
- **Workaround used / available:** Delete the target database before re-running load_runbook.sh.
- **Evidence:**

  `G-09(H21)`

  ```text
  runbook runs `gcloud spanner databases create` unconditionally under `set -euo pipefail` (no existence check: True); resume/skip-stage support: False. A re-run after success fails at stage 1; a failure after stage 3 cannot be resumed without dropping the DB.
  ```

### DEF-017 — Out-of-range dates crash / corrupt export

- **Hypothesis:** H22 · **Severity:** P1 · **Status:** Confirmed
- **Tests:** D-15
- **Workaround used / available:** Clamp/convert out-of-range dates in Neo4j before export.
- **Evidence:**

  `D-15`

  ```text
  export succeeded; CSV: ['y0,<neo4j._codec.hydration._common.BrokenHydrationObject object at 0x7f1758578f50>', 'y1,2020-01-01']
  ```

### DEF-018 — Original property/label names starting with a digit break CREATE PROPERTY GRAPH

- **Hypothesis:** NEW-DIGITNAME · **Severity:** P1 · **Status:** Confirmed
- **Tests:** C-05(T2)/F-01[G3]
- **Workaround used / available:** Rename such properties/labels in Neo4j before export (column_renames does not change the graph property name).
- **Evidence:**

  `C-05(T2)/F-01[G3]`

  ```text
  G3 bundle: 05_property_graph.sql rejected by Spanner: "Syntax error on line 6, column 56: Expecting EOF but found an unknown character (\`)" -> position is the alias `1st` in PROPERTIES (id_1st AS `1st`). Spanner DDL does not accept a quoted identifier that starts with a digit, but the tool preserves original Neo4j property names verbatim as graph property names. Isolated by probes: labels containing " ; -- are all accepted.
  ```

### DEF-019 — A single rejected row makes the Dataflow load hang (no invalidOutputPath); oversized values not detected

- **Hypothesis:** NEW-HANG · **Severity:** P1 · **Status:** Confirmed
- **Tests:** D-08(T3:r4), G-01[r2]/E-07(T3)
- **Workaround used / available:** Trim values > 2,621,440 chars (STRING) before export; add `invalidOutputPath=gs://...` to the runbook's Dataflow parameters.
- **Evidence:**

  `G-01[r2]/E-07(T3)`

  ```text
  R2 nodes Dataflow job 2026-11-18_18_15_03-12830543361029124285 loaded 23/24 VStr rows; the row with a 10,380,918-char string (STRING(MAX) limit is 2,621,440 characters) was rejected by Spanner. The runbook does not pass `invalidOutputPath`, so the template's 'Write failed Spanner records' step tried to finalize into the worker-local filesystem and spent >45 min in LocalFileSystem.match/File.isDirectory (stack in Cloud Logging, 'Operation ongoing in bundle ...Finalize'). Job never failed; cancelled by the harness after 46 min. Neither discovery nor export warned about the oversized value.
  ```

  `D-08(T3:r4)`

  ```text
  R4 nodes job 2026-11-18_18_52_50-15698955132928148999: rows with fl_val [1.5,NaN] / [Infinity,2.0] (invalid JSON) were rejected; job then hung >25 min in 'Write failed Spanner records ... Finalize' (LocalFileSystem.match) exactly like R2; cancelled by harness. Second independent reproduction.
  ```

### DEF-020 — load_runbook.sh fails for graphs without relationships (missing edges/ directory)

- **Hypothesis:** NEW-NOEDGE · **Severity:** P1 · **Status:** Confirmed
- **Tests:** G-10(nodes-only)
- **Workaround used / available:** `mkdir -p export_out/edges && touch` a placeholder, or add at least one relationship (used in R4).
- **Evidence:**

  `G-10(nodes-only)`

  ```text
  exporter writes no edges/ dir when there are no relationships, but the runbook always runs `gcloud storage cp --recursive .../edges` under set -e (True) and always launches the edges Dataflow job (True). Observed in T3: ['ERROR: (gcloud.storage.cp) The following URLs matched no objects or files:', '/tmp/rb/rb-20261119-015500-a1b2/t3_g02/export_out/edges']
  ```

### DEF-021 — Tab delimiter is accepted by export but breaks the Dataflow load

- **Hypothesis:** NEW-TAB · **Severity:** P1 · **Status:** Confirmed
- **Tests:** E-06(T3:r3)
- **Workaround used / available:** Use a printable single-character delimiter such as '|' or ';'.
- **Evidence:**

  `E-06(T3:r3)`

  ```text
  export --delimiter '\t' is accepted (SerializerConfig maps it to a TAB char) and CSVs are tab-delimited, but load_runbook.sh passes columnDelimiter=\t (2 chars) to GCS_Text_to_Cloud_Spanner. Dataflow job 2026-11-18_18_52_48-11397340451431987972 failed: 'InvalidFormatException: Cannot deserialize value of type java.lang.Character from String "\t": Expected either Integer value code or 1-character String'.
  ```

### DEF-022 — --emit-unescape generates invalid SQL (03_unescape.sql) and aborts the load

- **Hypothesis:** NEW-UNESCAPE · **Severity:** P1 · **Status:** Confirmed
- **Tests:** E-03(unescape)
- **Workaround used / available:** Do not use --emit-unescape; Dataflow already decodes the escapes (E-03 passed without it).
- **Evidence:**

  `E-03(unescape)`

  ```text
  With --emit-unescape, runbook stage 6 fails: gcloud spanner databases execute-sql INVALID_ARGUMENT 'Syntax error: Unclosed raw string literal' at ... '__BSLASH__', r'\') ... in 03_unescape.sql (a raw string cannot end with an odd backslash). The whole file is also passed as one --sql argument containing several statements. The opt-in fallback documented in README.md can never succeed (run rb_r1_02).
  ```

### DEF-023 — dst_ prefix exceeds 128 chars

- **Hypothesis:** H12 · **Severity:** P2 · **Status:** Confirmed
- **Tests:** C-08, C-08(T0)
- **Workaround used / available:** Use `column_renames` to keep destination PK column names <= 124 chars.
- **Evidence:**

  `C-08(T0)`

  ```text
  longest identifier token in DDL = 131 chars (dst_cccccc...)
  ```

  `C-08`

  ```text
  01_create_tables.sql: stmt#2 ERROR 400 Column name not valid: Src__R__Dst.dst_cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc. 3: Column name not valid: Src__R__Dst.dst_cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc. :: CREATE TABLE Src__R__Dst (
    id STRING(MAX) NOT NULL,
    dst_cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc STRING(MAX) NOT NULL
  ) PRIMARY KEY (id, dst_cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc),
    INTERLEAVE IN PARENT Src ON DELETE CASCADE
  04_constraints_indexes.sql: stmt#0 ERROR 404 Table not found: Src__R__Dst 5: Table not found: Src__R__Dst :: ALTER TABLE Src__R__Dst ADD CONSTRAINT fk_Src__R__Dst_dst FOREIGN KEY (dst_cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc) REFERENCES Dst (cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc)
  04_constraints_indexes.sql: stmt#1 ERROR 404 Table not found: Src__R__Dst 5: Table not found: Src__R__Dst :: CREATE INDEX idx_Src__R__Dst_rev ON Src__R__Dst (dst_cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
  ```

### DEF-024 — Backtick escaping in graph DDL

- **Hypothesis:** H13 · **Severity:** P2 · **Status:** Confirmed
- **Tests:** C-09
- **Workaround used / available:** Avoid backticks in labels/properties, or rename them.
- **Evidence:**

  `C-09`

  ```text
  05_property_graph.sql: stmt#0 ERROR 400 Error analyzing the definition of graph `RbGraph`: Syntax error: Expected \")\" or \",\" but got identifier `ird\\Label` [at 5:15]\n    LABEL `We``ird\\Label`\n              ^ 3: Error analyzing the definition of graph `RbGraph`: Syntax error: Expected \")\" or \",\" but got identifier `ird\\Label` [at 5:15]\n    LABEL `We``ird\\Label`\n              ^ :: CREATE OR REPLACE PROPERTY GRAPH RbGraph
  NODE TABLES (
    WeirdLabel
      KEY (wid)
      LABEL `We``ird\Label`
      PROPERTIES (wid AS `w``id\x`)
  )
  ```

### DEF-025 — Delimiter '~' breaks Dataflow parameter separator

- **Hypothesis:** H14 · **Severity:** P2 · **Status:** Confirmed
- **Tests:** G-06
- **Workaround used / available:** Do not use '~' as delimiter or inside --null-string.
- **Evidence:**

  `G-06`

  ```text
  columnDelimiter seen by Dataflow=''; parsed params=[{'instanceId': 'YOUR_SPANNER_INSTANCE', 'databaseId': 'neo4j_graph', 'importManifest': 'gs://b/run/manifests/nodes_manifest.json', 'columnDelimiter': '', '': '', 'fieldQualifier': '"', 'escape': '\\', 'nullString': '__NULL__', 'trailingDelimiter': 'false'}]
  ```

### DEF-026 — 0-row table -> manifest glob matches nothing

- **Hypothesis:** H17 · **Severity:** P2 · **Status:** Confirmed
- **Tests:** K-03
- **Workaround used / available:** Re-run discovery immediately before export (quiesced DB).
- **Evidence:**

  `K-03`

  ```text
  0-row table: no error, shards=0, manifest still lists 'Gone_part_*.csv' (True); Dataflow behaviour on an empty glob not tested (GCP fault tests out of scope)
  ```

### DEF-027 — verify sampling limited to first 50k rows

- **Hypothesis:** H20 · **Severity:** P2 · **Status:** Confirmed
- **Tests:** H-07
- **Workaround used / available:** Pass --sample-rows larger than the biggest table (verify then reads up to 5x rows).
- **Evidence:**

  `H-07`

  ```text
  row E059999 (last PK range of 60k-row table) corrupted; detected per seed: {1: (0, False), 42: (0, False), 7: (0, False)} (verify reads only first max(n*5,50000) rows)
  ```

### DEF-028 — Spanner column limit not detected

- **Hypothesis:** H23 · **Severity:** P2 · **Status:** Confirmed
- **Tests:** F-04
- **Workaround used / available:** Split very wide labels before export.
- **Evidence:**

  `F-04`

  ```text
  tool emitted a 1,100-column table without warning; Spanner: 01_create_tables.sql: stmt#0 ERROR 400 Table Wide has too many columns; the limit is 1024. 9: Table Wide has too many columns; the limit is 1024. :: CREATE TABLE Wide (
    wid STRING(MAX) NOT NULL,
    c0000 INT64,
    c0001 INT64,
    c0002 INT64,
    c0003 INT64,
    c0004 INT64,
    c0005 INT64,
    c0006 INT64,
    c0007 INT64,
    c0008 INT64,
    c0009 INT64,
    c0010 INT64,
    c0011 INT64,
    c0012 INT64,
    c0013 INT64,
    c0014 INT64,
    c0015 INT64,
    c0016 INT64,
    c0017 INT64,
    c0018 INT64,
    c0019 INT64,
    c0020 INT64,
    c0021 INT64,
    c0022 INT64,
    c0023 INT64,
    c0024 INT64,
    c0025 INT64,
    c0026 INT64,
    c0027 INT64,
    c0028 INT64,
    c0029 INT64,
    c0030 INT64,
    c0031 INT64,
    c0032 INT64,
    c0033 INT64,
    c0034 INT64,
    c0035 INT64,
    c0036 INT6
  05_property_graph.sql: stmt#0 ERROR 400 Error analyzing the definition of graph `RbGraph`: Table not found: Wide [at 3:5]\n    Wide\n    ^ 3: Error analyzing the definition of graph `RbGraph`: Table not found: Wide [at 3:5]\n    Wide\n    ^ :: CREATE OR REPLACE PROPERTY GRAPH RbGraph
  NODE TABLES (
    Wide
      KEY (wid)
      LABEL `Wide`
      PROPERTIES (wid AS `wid`, c0000 AS `c0000`, c0001 AS `c0001`, c0002 AS `c0002`, c0003 AS `c0003`, c0004 AS `c0004`, c0005 AS `c0005`, c0006 AS `c0006`, c0007 AS `c0007`, c0008 AS `c0008`, c0009 AS `c0009`, c0010 AS `c0010`, c0011 AS `c0011`, c0012 AS `c0012`, c0013 AS `c0013`, c0014 AS `c0014`, c0015 AS `c0015`, c0016 AS `c0016`, c0017 AS `c0017`, c0018 AS `c0018`, c0019 AS `c0019`, c0020 AS `c0020`, c0021
  ```

### DEF-029 — Empty DB -> invalid NODE TABLES ()

- **Hypothesis:** H25 · **Severity:** P2 · **Status:** Confirmed
- **Tests:** B-14[v44], B-14[v5]
- **Workaround used / available:** Do not run against an empty database.
- **Evidence:**

  `B-14[v5]`

  ```text
  empty DB accepted: 0 tables; 05_property_graph.sql = '-- Stage 05: Create Spanner Property Graph `MigratedGraph`.\nCREATE OR REPLACE PROPERTY GRAPH MigratedGraph\nNODE TABLES (\n\n)\n;\n'
  ```

  `B-14[v44]`

  ```text
  empty DB accepted: 0 tables; 05_property_graph.sql = '-- Stage 05: Create Spanner Property Graph `MigratedGraph`.\nCREATE OR REPLACE PROPERTY GRAPH MigratedGraph\nNODE TABLES (\n\n)\n;\n'
  ```

### DEF-030 — Unknown/missing YAML keys -> raw TypeError

- **Hypothesis:** H26 · **Severity:** P2 · **Status:** Confirmed
- **Tests:** A-04[missing_field], A-04[unknown_key]
- **Workaround used / available:** Edit schema_mapping.yaml carefully; re-run discovery to regenerate it.
- **Evidence:**

  `A-04[unknown_key]`

  ```text
  rc=1 traceback=True tail=l/src/neo4j_spanner_export/cli.py", line 58, in _cmd_export
      mapping = load_mapping(args.mapping)
    File "/usr/local/google/home/jicong/work/neo4j-migration-tool/src/neo4j_spanner_export/config.py", line 129, in load_mapping
      return SchemaMapping.from_dict(data)
             ~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
    File "/usr/local/google/home/jicong/work/neo4j-migration-tool/src/neo4j_spanner_export/config.py", line 91, in from_dict
      nodes[k] = NodeTableMapping(**v_copy)
                 ~~~~~~~~~~~~~~~~^^^^^^^^^^
  TypeError: NodeTableMapping.__init__() got an unexpected keyword argument 'colour'
  
  ```

  `A-04[missing_field]`

  ```text
  rc=1 traceback=True tail=spanner_export/cli.py", line 58, in _cmd_export
      mapping = load_mapping(args.mapping)
    File "/usr/local/google/home/jicong/work/neo4j-migration-tool/src/neo4j_spanner_export/config.py", line 129, in load_mapping
      return SchemaMapping.from_dict(data)
             ~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
    File "/usr/local/google/home/jicong/work/neo4j-migration-tool/src/neo4j_spanner_export/config.py", line 91, in from_dict
      nodes[k] = NodeTableMapping(**v_copy)
                 ~~~~~~~~~~~~~~~~^^^^^^^^^^
  TypeError: NodeTableMapping.__init__() missing 1 required positional argument: 'spanner_table'
  
  ```

### DEF-031 — schema_mapping.yaml not byte-identical across Neo4j versions

- **Hypothesis:** NEW-DET · **Severity:** P2 · **Status:** Confirmed
- **Tests:** F-11b
- **Workaround used / available:** Compare mappings semantically, not byte-wise.
- **Evidence:**

  `F-11b`

  ```text
  mapping differs only by creation order; diff lines: ['-    monotonic_pk_warning: true', '+    monotonic_pk_warning: false', '+          INT64: 20', '-          INT64: 20']
  ```

### DEF-032 — An empty schema_mapping.yaml exports 0 rows with exit code 0

- **Hypothesis:** NEW-EMPTY · **Severity:** P2 · **Status:** Confirmed
- **Tests:** A-04[empty_file]
- **Workaround used / available:** Always check the 'Export complete' row counts.
- **Evidence:**

  `A-04[empty_file]`

  ```text
  An empty schema_mapping.yaml is accepted by `export`, which exits 0 and reports 'Export complete: 0 node row(s), 0 edge row(s)'. An empty schema_mapping.yaml is accepted by `export`, which exits 0 and reports 'Export complete: 0 node row(s), 0 edge row(s)'. rc=0 tail=Export complete: 0 node row(s), 0 edge row(s) -> 
  /tmp/pytest-of-jicong/pytest-10/test_A04_bad_yaml_clean_error_2/o
  
  ```

### DEF-033 — Empty BYTES values become NULL after load

- **Hypothesis:** NEW-EMPTYBYTES · **Severity:** P2 · **Status:** Confirmed
- **Tests:** D-19(T3:VBytes)
- **Workaround used / available:** Post-load DML for known empty-bytes rows, or represent empty bytes differently in Neo4j.
- **Evidence:**

  `D-19(T3:VBytes)`

  ```text
  Neo4j byte[] of length 0 (case 'empty') is exported as a quoted empty field and arrives in Spanner as NULL (golden expected b''). Non-empty BYTES (incl. \x00\xff and 5 MiB) round-trip exactly. Empty STRING '' is preserved (E-01), so only BYTES is affected.
  ```

### DEF-034 — Dataflow job names collide when two loads start in the same second

- **Hypothesis:** NEW-JOBNAME · **Severity:** P2 · **Status:** Confirmed
- **Tests:** G-11(job-name)
- **Workaround used / available:** Start concurrent runbooks a few seconds apart (harness staggers by 3 s).
- **Evidence:**

  `G-11(job-name)`

  ```text
  Dataflow job names are `neo4j-load-{nodes,edges}-$(date +%s)` (not unique per database/run): two runbooks started within the same second collide. Observed: ['ERROR: (gcloud.dataflow.jobs.run) ALREADY_EXISTS: (81d5770538f1b015): The workflow could not be created. Causes: (c523a660da998974): There is already an active job named neo4j-load-nodes-1795054514. If you want to submit a second job, try again by setting a different name.']
  ```

### DEF-035 — Node label and relationship type with the same name produce conflicting LABEL definitions

- **Hypothesis:** NEW-LABELCLASH · **Severity:** P2 · **Status:** Confirmed
- **Tests:** C-11
- **Workaround used / available:** Rename the label or relationship type in Neo4j before export.
- **Evidence:**

  `C-11`

  ```text
  05_property_graph.sql: stmt#0 ERROR 400 Error analyzing the definition of graph `RbGraph`: The label \'KNOWS\' is defined with different properties. One definition of the label has 0 property declarations: \'[]\'. Another definition has  1 property declarations: \'[kid]\'. You need to use the same set of property declarations under the same label [at 18:7]\n      LABEL KNOWS NO PROPERTIES\n      ^ 3: Error analyzing the definition of graph `RbGraph`: The label \'KNOWS\' is defined with different properties. One definition of the label has 0 property declarations: \'[]\'. Another definition has  1 property declarations: \'[kid]\' :: CREATE OR REPLACE PROPERTY GRAPH RbGraph
  NODE TABLES (
    KNOWS
      KEY (kid)
      LABEL `KNOWS`
      PROPERTIES (kid AS `kid`),
    Pz
      KEY (pid)
      LABEL `Pz`
      PROPERTIES (pid AS `pid`)
  )
  EDGE TABLES (
    Pz__KNOWS__KNOWS
      KEY (pid, dst_kid)
      SOURCE KEY (pid) REFERENCES Pz (pid)
      DESTINATION KEY (dst_kid) REFERENCES KNOWS (kid)
      LABEL `KNOWS`
      NO PROPERTIES
  )
  ```

### DEF-036 — Monotonic-PK hotspot warning depends on Neo4j scan order

- **Hypothesis:** NEW-MONO · **Severity:** P2 · **Status:** Confirmed
- **Tests:** B-15
- **Workaround used / available:** Review discovery_report.md manually for sequential business keys.
- **Evidence:**

  `B-15`

  ```text
  sequential INT64 PK 1..50: warn=False; random UUID PK: warn=False (heuristic inspects internal scan order, not key values; store order differs after deletes)
  ```

### DEF-037 — Values above Spanner limits (STRING 2,621,440 chars / 10 MiB) are not detected before load

- **Hypothesis:** NEW-SIZE · **Severity:** P2 · **Status:** Confirmed
- **Tests:** E-07
- **Workaround used / available:** Check max property sizes in Neo4j before export (`size(n.prop) > 10*1024*1024`).
- **Evidence:**

  `E-07`

  ```text
  2,700,000-char string exported without warning (rows=1); Spanner STRING(MAX) limit is 2,621,440 chars (10 MiB for BYTES); in T3 such a row was rejected and hung the Dataflow job (NEW-HANG)
  ```

### DEF-038 — CLI surfaces operational/validation errors as raw Python tracebacks

- **Hypothesis:** NEW-UX · **Severity:** P2 · **Status:** Confirmed
- **Tests:** A-02, A-03, A-05, A-10, H-09
- **Workaround used / available:** None needed for correctness; read the last traceback line.
- **Evidence:**

  `A-02`

  ```text
  {'wrong_password': {'rc': 1, 'traceback': True, 'partial_file': False, 'last': 'neo4j.exceptions.AuthError: {code: Neo.ClientError.Security.Unauthorized} {message: The client is unauthorized due to authentication failure.}'}, 'unreachable': {'rc': 1, 'traceback': True, 'partial_file': False, 'last': "Failed to establish connection to ResolvedIPv4Address(('127.0.0.1', 1)) (reason [Errno 111] Connection refused)"}, 'tls_mismatch': {'rc': 1, 'traceback': True, 'partial_file': False, 'last': 'neo4j.exceptions.ServiceUnavailable: Unable to retrieve routing information'}}
  ```

  `A-03`

  ```text
  rc=1 traceback=True last=neo4j.exceptions.ClientError: {code: Neo.ClientError.Database.DatabaseNotFound} {message: Graph not found: nosuchdb}
  ```

  `A-05`

  ```text
  {'chunk0': (1, True, 'ValueError: chunk_rows must be > 0, got 0'), 'workers_neg': (0, False, '/tmp/rb/rb-20261119-015500-a1b2/test_A05_chunk_rows_and_workers/workers_neg'), 'workers64': (0, False, '/tmp/rb/rb-20261119-015500-a1b2/test_A05_chunk_rows_and_workers/workers64')}
  ```

  `A-10`

  ```text
  rc=1 last=zoneinfo._common.ZoneInfoNotFoundError: 'No time zone found with key Mars/Base'
  ```

