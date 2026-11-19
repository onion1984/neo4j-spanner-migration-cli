# Defect log

Run: `rb-20261119-044800-c2d3` · generated from `findings.jsonl` (latest record per test).

| DEF | Hypothesis | Severity | Title | Tests |
| :--- | :--- | :--- | :--- | :--- |
| DEF-001 | NEW-DISCCRASH | P0 | discover crashes on every non-empty graph (UnboundLocalError: fixed_cols_lower, discovery.py:353) | BLOCKED:test_A05_chunk_rows_and_workers, BLOCKED:test_A06_sample_size_type_drift, BLOCKED:test_A10_invalid_timezone_cli, BLOCKED:test_B04_label_priority_unknown_and_duplicate[v44], BLOCKED:test_B04_label_priority_unknown_and_duplicate[v5], BLOCKED:test_B05_B06_partition_invariants[v44], BLOCKED:test_B05_B06_partition_invariants[v5], BLOCKED:test_B08_uniqueness_with_nulls_falls_back[v44], BLOCKED:test_B08_uniqueness_with_nulls_falls_back[v5], BLOCKED:test_B09_pk_override_with_duplicates, BLOCKED:test_B10_pk_override_illegal_types, BLOCKED:test_B11_mixed_type_unique_key_collision, BLOCKED:test_B12_constraint_on_secondary_label, BLOCKED:test_B15_monotonic_heuristic, BLOCKED:test_B16_parallel_edge_detection[v44], BLOCKED:test_B16_parallel_edge_detection[v5], BLOCKED:test_C01_reserved_keywords_fail_fast_and_rename[v44], BLOCKED:test_C01_reserved_keywords_fail_fast_and_rename[v5], BLOCKED:test_C03_case_collisions[v44], BLOCKED:test_C03_case_collisions[v5], BLOCKED:test_C04_unicode_names_collide, BLOCKED:test_C05_C09_special_names_preserved[v44], BLOCKED:test_C05_C09_special_names_preserved[v5], BLOCKED:test_C06_long_names_deterministic[v44], BLOCKED:test_C06_long_names_deterministic[v5], BLOCKED:test_C10_fixed_column_collisions, BLOCKED:test_D03_sparse_property_null_counts, BLOCKED:test_D10_int64_override_truncates_in_export, BLOCKED:test_E02_sentinel_collision, BLOCKED:test_E07_oversize_cell_detection, BLOCKED:test_F11b_mapping_independent_of_store_order, BLOCKED:test_I01_F11_A09_parity_and_determinism[g5], BLOCKED:test_I01_F11_A09_parity_and_determinism[r2], BLOCKED:test_I04_neo4j_routing_scheme, BLOCKED:test_L01_password_not_logged, BLOCKED:test_L02_malicious_names[v44], BLOCKED:test_L02_malicious_names[v5] |
| DEF-002 | NEW-TAB | P0 | Tab delimiter breaks the Dataflow load (campaign 2: silent corruption, columnDelimiter=9 treated as the character '9') | E-06(T3:r3) |
| DEF-003 | H10 | P1 | Secondary labels not queryable as GQL labels | F-09 |
| DEF-004 | H19 | P1 | verify false missing_in_neo4j for widened/TIMESTAMP/BYTES PKs | H-06 |
| DEF-005 | NEW-INPUTMAP | P1 | Partial --input-mapping files (renames / label_priority / pk_overrides) are rejected by load_mapping validation | A-09b[v44], A-09b[v5] |
| DEF-006 | NEW-LABELRENAME | P1 | table_renames now also renames the graph LABEL, losing the original Neo4j label (verify queries fail) | H-06(LABEL) |
| DEF-007 | NEW-SILENTREJECT | P1 | Rows rejected by Dataflow are written to invalid_records/ but the runbook still reports success | D-16(T3:r2,silent) |
| DEF-008 | NEW-VERIFYBYTES | P1 | verify reports false mismatches for all BYTES values and BYTES primary keys (no base64 decode) | H-06(BYTES) |
| DEF-009 | NEW-YEARPAD | P1 | TIMESTAMP values with year < 1000 are serialized without zero padding and rejected by Spanner | D-16(T3:VDateTime) |
| DEF-010 | H13 | P2 | Backtick escaping in graph DDL | C-09 |
| DEF-011 | NEW-UX | P2 | CLI surfaces operational/validation errors as raw Python tracebacks | A-02 |
| DEF-012 | NEW-VERIFYFLOAT | P2 | verify flags equal FLOAT64 values as mismatches when Neo4j stored them as integers | H-06(FLOAT) |

### DEF-001 — discover crashes on every non-empty graph (UnboundLocalError: fixed_cols_lower, discovery.py:353)

- **Hypothesis:** NEW-DISCCRASH · **Severity:** P0 · **Status:** Confirmed
- **Tests:** BLOCKED:test_A05_chunk_rows_and_workers, BLOCKED:test_A06_sample_size_type_drift, BLOCKED:test_A10_invalid_timezone_cli, BLOCKED:test_B04_label_priority_unknown_and_duplicate[v44], BLOCKED:test_B04_label_priority_unknown_and_duplicate[v5], BLOCKED:test_B05_B06_partition_invariants[v44], BLOCKED:test_B05_B06_partition_invariants[v5], BLOCKED:test_B08_uniqueness_with_nulls_falls_back[v44], BLOCKED:test_B08_uniqueness_with_nulls_falls_back[v5], BLOCKED:test_B09_pk_override_with_duplicates, BLOCKED:test_B10_pk_override_illegal_types, BLOCKED:test_B11_mixed_type_unique_key_collision, BLOCKED:test_B12_constraint_on_secondary_label, BLOCKED:test_B15_monotonic_heuristic, BLOCKED:test_B16_parallel_edge_detection[v44], BLOCKED:test_B16_parallel_edge_detection[v5], BLOCKED:test_C01_reserved_keywords_fail_fast_and_rename[v44], BLOCKED:test_C01_reserved_keywords_fail_fast_and_rename[v5], BLOCKED:test_C03_case_collisions[v44], BLOCKED:test_C03_case_collisions[v5], BLOCKED:test_C04_unicode_names_collide, BLOCKED:test_C05_C09_special_names_preserved[v44], BLOCKED:test_C05_C09_special_names_preserved[v5], BLOCKED:test_C06_long_names_deterministic[v44], BLOCKED:test_C06_long_names_deterministic[v5], BLOCKED:test_C10_fixed_column_collisions, BLOCKED:test_D03_sparse_property_null_counts, BLOCKED:test_D10_int64_override_truncates_in_export, BLOCKED:test_E02_sentinel_collision, BLOCKED:test_E07_oversize_cell_detection, BLOCKED:test_F11b_mapping_independent_of_store_order, BLOCKED:test_I01_F11_A09_parity_and_determinism[g5], BLOCKED:test_I01_F11_A09_parity_and_determinism[r2], BLOCKED:test_I04_neo4j_routing_scheme, BLOCKED:test_L01_password_not_logged, BLOCKED:test_L02_malicious_names[v44], BLOCKED:test_L02_malicious_names[v5]
- **Workaround used / available:** None at input level. Re-use a schema_mapping.yaml generated by an earlier version (used by this re-test for export/load/verify).
- **Evidence:**

  `BLOCKED:test_B04_label_priority_unknown_and_duplicate[v5]`

  ```text
  discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not run
  ```

  `BLOCKED:test_B08_uniqueness_with_nulls_falls_back[v5]`

  ```text
  discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not run
  ```

  `BLOCKED:test_B16_parallel_edge_detection[v5]`

  ```text
  discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not run
  ```

  `BLOCKED:test_C01_reserved_keywords_fail_fast_and_rename[v5]`

  ```text
  discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not run
  ```

### DEF-002 — Tab delimiter breaks the Dataflow load (campaign 2: silent corruption, columnDelimiter=9 treated as the character '9')

- **Hypothesis:** NEW-TAB · **Severity:** P0 · **Status:** Confirmed
- **Tests:** E-06(T3:r3)
- **Workaround used / available:** Use a printable single-character delimiter such as '|' or ';'.
- **Evidence:**

  `E-06(T3:r3)`

  ```text
  R3 exported with --delimiter '\t'; runbook now passes columnDelimiter=9 and exits 0 ('Load complete!'), but the template treats '9' as the literal character '9': Spanner holds Company 45/50, Person 1296/2000, Event 39366/60000, Post 243/300, Lonely 0/2 and 0 rows in all 9 edge tables; keys contain whole tab-joined lines, e.g. cid='C041\tCo 41', pid='P01338\t36\tPerson 1338\t[]', eid='E012716\t12716'. Failure mode changed from a failed job (campaign 1) to SILENT corruption; only verify's counts reveal it.
  ```

### DEF-003 — Secondary labels not queryable as GQL labels

- **Hypothesis:** H10 · **Severity:** P1 · **Status:** Confirmed
- **Tests:** F-09
- **Workaround used / available:** Query `WHERE 'Label' IN UNNEST(n.secondary_labels)` instead of `MATCH (n:Label)`.
- **Evidence:**

  `F-09`

  ```text
  Cypher MATCH (n:Employee) -> 200; GQL MATCH (n:Employee) -> ERROR 400 Failed to find element label [Employee] in PropertyGraph: RbR3 [at 1:21]\nGRAPH RbR3 MATCH (n:Employee) RETURN COUNT(*) AS c\n                    ^, request_id = 1.1844002745570446012.1.21.44.1 [l; workaround via secondary_labels -> 200
  ```

### DEF-004 — verify false missing_in_neo4j for widened/TIMESTAMP/BYTES PKs

- **Hypothesis:** H19 · **Severity:** P1 · **Status:** Confirmed
- **Tests:** H-06
- **Workaround used / available:** Interpret verify sample failures on such tables manually.
- **Evidence:**

  `H-06`

  ```text
  Partially fixed. Clean R2 DB: verify no longer crashes (report written) and TIMESTAMP-PK lookups now work (PkTs has no false misses). Still false `missing_in_neo4j`: (a) BYTES PKs - PkBytes 10/10 and PkFloat__REL_D__PkBytes 10/10 (base64 not decoded, see NEW-VERIFYBYTES); (b) widened STRING PKs - PkWide wk '1','2','3' (Neo4j stores ints) and PkTs__REL_B__PkWide 9/9 via dst_wk.
  ```

### DEF-005 — Partial --input-mapping files (renames / label_priority / pk_overrides) are rejected by load_mapping validation

- **Hypothesis:** NEW-INPUTMAP · **Severity:** P1 · **Status:** Confirmed
- **Tests:** A-09b[v44], A-09b[v5]
- **Workaround used / available:** Pass label_priority via --label-priority; give every hand-written node entry its PK property (and a node entry for each pk_overrides label).
- **Evidence:**

  `A-09b[v5]`

  ```text
  {'label_priority_only': 'ConfigError: Schema mapping defines 0 node tables; nothing to export or generate.', 'pk_overrides_only': 'ConfigError: Schema mapping defines 0 node tables; nothing to export or generate.', 'node_column_renames': "ConfigError: Primary key column '_neo4j_id' missing from A.properties."}
  ```

  `A-09b[v44]`

  ```text
  {'label_priority_only': 'ConfigError: Schema mapping defines 0 node tables; nothing to export or generate.', 'pk_overrides_only': 'ConfigError: Schema mapping defines 0 node tables; nothing to export or generate.', 'node_column_renames': "ConfigError: Primary key column '_neo4j_id' missing from A.properties."}
  ```

### DEF-006 — table_renames now also renames the graph LABEL, losing the original Neo4j label (verify queries fail)

- **Hypothesis:** NEW-LABELRENAME · **Severity:** P1 · **Status:** Confirmed
- **Tests:** H-06(LABEL)
- **Workaround used / available:** Avoid table_renames on labels used by queries, or query the renamed label.
- **Evidence:**

  `H-06(LABEL)`

  ```text
  With table_renames {Order: Orders}, 05_property_graph.sql now declares LABEL `Orders` (node_label_alias = table_renames.get(raw_label)) instead of the original Neo4j label `Order`. README promises original label names in CREATE PROPERTY GRAPH; GQL `MATCH (n:Order)` fails ('Failed to find element label [Order]') and verify's own default queries count_node_Orders / hop1_*__Order fail on R1.
  ```

### DEF-007 — Rows rejected by Dataflow are written to invalid_records/ but the runbook still reports success

- **Hypothesis:** NEW-SILENTREJECT · **Severity:** P1 · **Status:** Confirmed
- **Tests:** D-16(T3:r2,silent)
- **Workaround used / available:** After each load, check `gcloud storage ls ${GCS_PREFIX}/invalid_records/` and run verify (counts catch the gap).
- **Evidence:**

  `D-16(T3:r2,silent)`

  ```text
  R2 runbook exited 0 with 'Load complete!' although Dataflow wrote 1 rejected row to gs://jicong/neo4j-robust/rb-20261119-044800-c2d3/r2/invalid_records/ (VDateTime 'min'). The runbook never inspects invalidOutputPath, so rejected rows are lost silently unless verify is run.
  ```

### DEF-008 — verify reports false mismatches for all BYTES values and BYTES primary keys (no base64 decode)

- **Hypothesis:** NEW-VERIFYBYTES · **Severity:** P1 · **Status:** Confirmed
- **Tests:** H-06(BYTES)
- **Workaround used / available:** Ignore verify BYTES mismatches; validate BYTES with an independent check.
- **Evidence:**

  `H-06(BYTES)`

  ```text
  verify now compares BYTES without base64-decoding the Spanner client value: R1 Product.payload expected b'abc' vs actual b'YWJj'; R2 VBytes nul_ff expected b'\x00\xff\x00' vs actual b'AP8A'; PkBytes and PkFloat__REL_D__PkBytes rows all reported missing_in_neo4j (PK param passed as base64 text). Every non-empty BYTES value is a false mismatch (campaign 1 decoded correctly).
  ```

### DEF-009 — TIMESTAMP values with year < 1000 are serialized without zero padding and rejected by Spanner

- **Hypothesis:** NEW-YEARPAD · **Severity:** P1 · **Status:** Confirmed
- **Tests:** D-16(T3:VDateTime)
- **Workaround used / available:** None at input level; verify counts reveal the missing rows.
- **Evidence:**

  `D-16(T3:VDateTime)`

  ```text
  VDateTime 'min' = datetime('0001-01-01T00:00:00Z') exported as '1-01-01T00:00:00Z' (new _format_neo4j_datetime_utc uses strftime('%Y'), which does not zero-pad years < 1000 on Linux). Spanner rejected the row (written to gs://jicong/neo4j-robust/rb-20261119-044800-c2d3/r2/invalid_records/nodes-00000-of-00001-...-spanner-depth-0.csv); VDateTime has 8/9 rows. Campaign 1 loaded it correctly (regression).
  ```

### DEF-010 — Backtick escaping in graph DDL

- **Hypothesis:** H13 · **Severity:** P2 · **Status:** Confirmed
- **Tests:** C-09
- **Workaround used / available:** Avoid backticks in labels/properties, or rename them.
- **Evidence:**

  `C-09`

  ```text
  backtick+backslash: REJECTED by tool before Spanner: NamingError: Spanner Graph LABEL alias 'We`ird\\Label' in node table 'WeirdLabel' cannot start with a digit or contain '\'. Add a rename under `table_renames` in schema_mapping.yaml. || backtick only: 05_property_graph.sql: stmt#0 ERROR 400 Error analyzing the definition of graph `RbGraph`: Syntax error: Expected \")\" or \",\" but got identifier `ird` [at 5:15]\n    LABEL `We``ird`\n              ^ 3: Error analyzing the definition of graph `RbGraph`: Syntax error: Expected \")\" or \",\" but got identifier `ird` [at 5:15]\n    LABEL `We``ird`\n              ^ :: CREATE OR REPLACE PROPERTY GRAPH RbGraph
  NODE TABLES (
    WeirdLabel2
      KEY (wid)
      LABEL `We``ird`
      PROPERTIES (wid AS `w``id`)
  )
  ```

### DEF-011 — CLI surfaces operational/validation errors as raw Python tracebacks

- **Hypothesis:** NEW-UX · **Severity:** P2 · **Status:** Confirmed
- **Tests:** A-02
- **Workaround used / available:** None needed for correctness; read the last traceback line.
- **Evidence:**

  `A-02`

  ```text
  {'wrong_password': {'rc': 1, 'traceback': False, 'partial_file': False, 'last': 'unauthorized due to authentication failure.}'}, 'unreachable': {'rc': 1, 'traceback': True, 'partial_file': False, 'last': "Failed to establish connection to ResolvedIPv4Address(('127.0.0.1', 1)) (reason [Errno 111] Connection refused)"}, 'tls_mismatch': {'rc': 1, 'traceback': True, 'partial_file': False, 'last': 'neo4j.exceptions.ServiceUnavailable: Unable to retrieve routing information'}}
  ```

### DEF-012 — verify flags equal FLOAT64 values as mismatches when Neo4j stored them as integers

- **Hypothesis:** NEW-VERIFYFLOAT · **Severity:** P2 · **Status:** Confirmed
- **Tests:** H-06(FLOAT)
- **Workaround used / available:** Ignore int-vs-float mismatches in verify output.
- **Evidence:**

  `H-06(FLOAT)`

  ```text
  verify _values_equal now requires identical Python types when either side is int: TConf.c_lif ARRAY<FLOAT64> expected [1, 2] (Neo4j ints) vs actual [1.0, 2.0] reported as a mismatch although the values are equal and correctly stored.
  ```

