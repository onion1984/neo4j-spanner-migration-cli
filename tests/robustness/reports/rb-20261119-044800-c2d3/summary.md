# Robustness test summary

Run: `rb-20261119-044800-c2d3`

Records: {'Pass': 53, 'Refuted': 58, 'Observation': 5, 'Not testable': 2, 'Confirmed': 49, 'Out of scope': 4} · Hypotheses: Confirmed=12, Refuted=32, Not testable=0, Out of scope=2, Observation=1

## Hypothesis matrix

| Hypothesis | Description | Status | Tests | Defect |
| :--- | :--- | :--- | :--- | :--- |
| H01 | verify cannot catch coercion bugs (shares coerce_value()) | **Refuted** | H-01, H-01(golden-vs-verify) | — |
| H02 | DateTime ns truncated to µs; verify compares only to ms | **Refuted** | D-14(T0), D-14(T3:VDateTime), H-04 | — |
| H03 | INT64+FLOAT64 widening loses precision > 2^53; verify isclose hides it | **Refuted** | D-05, D-05(T3:TConf), D-13(T3:VListInt), H-05 | — |
| H04 | Type overrides not validated (truncation / silent false / invalid DDL types) | **Refuted** | A-08, A-08(T2), D-10, D-11 | — |
| H05 | pk_overrides not checked for uniqueness or legal PK type | **Refuted** | B-10(T2) | — |
| H06 | Mixed-type unique keys collapse to duplicate STRING PKs | **NOT RUN** |  | — |
| H07 | NaN/Infinity inside lists -> invalid JSON | **Refuted** | D-08, D-08(T3)/G-04 | — |
| H08 | Same property name, different types across node labels breaks graph DDL | **Refuted** | F-05 | — |
| H09 | Conflicting ARRAY/JSON types on a shared edge label emit an invalid CAST (CAST(NULL AS STRING(MAX)) and INT->STRING are accepted) | **Refuted** | F-06, F-07 | — |
| H10 | Secondary labels not queryable as GQL labels | **Confirmed** | F-09 | DEF-003 |
| H11 | FK/index name truncation collisions | **Refuted** | C-07, C-07(T0) | — |
| H12 | dst_ prefix exceeds 128 chars | **Refuted** | C-08, C-08(T0) | — |
| H13 | Backtick escaping in graph DDL | **Confirmed** | C-09 | DEF-010 |
| H14 | Delimiter '~' breaks Dataflow parameter separator | **Refuted** | G-06 | — |
| H15 | --gcs-prefix / --graph-name injection | **Refuted** | F-08, L-03, L-04 | — |
| H16 | Stale shards loaded (local dir / GCS prefix) | **Refuted** | G-09(H16-GCS), K-05, K-10 | — |
| H17 | 0-row table -> manifest glob matches nothing | **Refuted** | K-03 | — |
| H18 | --sample-size type drift crashes export with partial bundle | **Refuted** | A-06(T1,manual-mapping) | — |
| H19 | verify false missing_in_neo4j for widened/TIMESTAMP/BYTES PKs | **Confirmed** | H-06 | DEF-004 |
| H20 | verify sampling limited to first 50k rows | **Refuted** | H-07 | — |
| H21 | Runbook not idempotent / no resume | **Refuted** | G-09(H21) | — |
| H22 | Out-of-range dates crash / corrupt export | **Refuted** | D-15, D-15(T0) | — |
| H23 | Spanner column limit not detected | **Refuted** | F-04(T1) | — |
| H24 | No driver timeout; stalled Neo4j hangs export | **Refuted** | K-01, K-02 | — |
| H25 | Empty DB -> invalid NODE TABLES () | **Refuted** | B-14[v44], B-14[v5], F-01[B14_nodes_only] | — |
| H26 | Unknown/missing YAML keys -> raw TypeError | **Refuted** | A-04[missing_field], A-04[unknown_key] | — |
| H27 | Writes during export -> dangling edges | **Out of scope** | K-04 | — |
| H28 | Neo4j 2025.x calendar versioning | **Out of scope** | I-03 | — |
| H29 | Multi-label partition drops/duplicates rows | **NOT RUN** |  | — |
| NEW-DIGITNAME | Original property/label names starting with a digit break CREATE PROPERTY GRAPH | **Refuted** | C-05(T0) | — |
| NEW-DISCCRASH | discover crashes on every non-empty graph (UnboundLocalError: fixed_cols_lower, discovery.py:353) | **Confirmed** | BLOCKED:test_A05_chunk_rows_and_workers, BLOCKED:test_A06_sample_size_type_drift, BLOCKED:test_A10_invalid_timezone_cli, BLOCKED:test_B04_label_priority_unknown_and_duplicate[v44], BLOCKED:test_B04_label_priority_unknown_and_duplicate[v5], BLOCKED:test_B05_B06_partition_invariants[v44], BLOCKED:test_B05_B06_partition_invariants[v5], BLOCKED:test_B08_uniqueness_with_nulls_falls_back[v44], BLOCKED:test_B08_uniqueness_with_nulls_falls_back[v5], BLOCKED:test_B09_pk_override_with_duplicates, BLOCKED:test_B10_pk_override_illegal_types, BLOCKED:test_B11_mixed_type_unique_key_collision, BLOCKED:test_B12_constraint_on_secondary_label, BLOCKED:test_B15_monotonic_heuristic, BLOCKED:test_B16_parallel_edge_detection[v44], BLOCKED:test_B16_parallel_edge_detection[v5], BLOCKED:test_C01_reserved_keywords_fail_fast_and_rename[v44], BLOCKED:test_C01_reserved_keywords_fail_fast_and_rename[v5], BLOCKED:test_C03_case_collisions[v44], BLOCKED:test_C03_case_collisions[v5], BLOCKED:test_C04_unicode_names_collide, BLOCKED:test_C05_C09_special_names_preserved[v44], BLOCKED:test_C05_C09_special_names_preserved[v5], BLOCKED:test_C06_long_names_deterministic[v44], BLOCKED:test_C06_long_names_deterministic[v5], BLOCKED:test_C10_fixed_column_collisions, BLOCKED:test_D03_sparse_property_null_counts, BLOCKED:test_D10_int64_override_truncates_in_export, BLOCKED:test_E02_sentinel_collision, BLOCKED:test_E07_oversize_cell_detection, BLOCKED:test_F11b_mapping_independent_of_store_order, BLOCKED:test_I01_F11_A09_parity_and_determinism[g5], BLOCKED:test_I01_F11_A09_parity_and_determinism[r2], BLOCKED:test_I04_neo4j_routing_scheme, BLOCKED:test_L01_password_not_logged, BLOCKED:test_L02_malicious_names[v44], BLOCKED:test_L02_malicious_names[v5] | DEF-001 |
| NEW-EMPTY | An empty schema_mapping.yaml exports 0 rows with exit code 0 | **Refuted** | A-04[empty_file] | — |
| NEW-EMPTYBYTES | Empty BYTES values become NULL after load | **Refuted** | D-19(T3:VBytes) | — |
| NEW-ENV |  | **Observation** | ENV(auth) | — |
| NEW-HANG | A single rejected row makes the Dataflow load hang (no invalidOutputPath); oversized values not detected | **Refuted** | E-07(T3:r2), E-07(T3:r5) | — |
| NEW-INPUTMAP | Partial --input-mapping files (renames / label_priority / pk_overrides) are rejected by load_mapping validation | **Confirmed** | A-09b[v44], A-09b[v5] | DEF-005 |
| NEW-JOBNAME | Dataflow job names collide when two loads start in the same second | **Refuted** | G-11(job-name) | — |
| NEW-LABELCLASH | Node label and relationship type with the same name produce conflicting LABEL definitions | **Refuted** | C-11 | — |
| NEW-LABELRENAME | table_renames now also renames the graph LABEL, losing the original Neo4j label (verify queries fail) | **Confirmed** | H-06(LABEL) | DEF-006 |
| NEW-MONO | Monotonic-PK hotspot warning depends on Neo4j scan order | **Refuted** | B-15(T0) | — |
| NEW-NOEDGE | load_runbook.sh fails for graphs without relationships (missing edges/ directory) | **Refuted** | G-10(T3:nodes-only), G-10(nodes-only) | — |
| NEW-SILENTREJECT | Rows rejected by Dataflow are written to invalid_records/ but the runbook still reports success | **Confirmed** | D-16(T3:r2,silent), E-07(T3:r5,silent) | DEF-007 |
| NEW-SIZE | Values above Spanner limits (STRING 2,621,440 chars / 10 MiB) are not detected before load | **Refuted** | E-07(T0) | — |
| NEW-TAB | Tab delimiter breaks the Dataflow load (campaign 2: silent corruption, columnDelimiter=9 treated as the character '9') | **Confirmed** | E-06(T3:r3) | DEF-002 |
| NEW-UNESCAPE | --emit-unescape generates invalid SQL (03_unescape.sql) and aborts the load | **Refuted** | E-03(unescape) | — |
| NEW-UX | CLI surfaces operational/validation errors as raw Python tracebacks | **Confirmed** | A-02, A-03, H-09, K-02(ux) | DEF-011 |
| NEW-VERIFYBYTES | verify reports false mismatches for all BYTES values and BYTES primary keys (no base64 decode) | **Confirmed** | H-06(BYTES) | DEF-008 |
| NEW-VERIFYFLOAT | verify flags equal FLOAT64 values as mismatches when Neo4j stored them as integers | **Confirmed** | H-06(FLOAT) | DEF-012 |
| NEW-YEARPAD | TIMESTAMP values with year < 1000 are serialized without zero padding and rejected by Spanner | **Confirmed** | D-16(T3:VDateTime) | DEF-009 |

## All test records (latest per test)

| Test | Hyp | Status | Evidence (truncated) |
| :--- | :--- | :--- | :--- |
| A-01 |  | Pass | rc=1 stderr=NEO4J_PASSWORD environment variable (or --password) is required.  |
| A-02 | NEW-UX | Confirmed | {'wrong_password': {'rc': 1, 'traceback': False, 'partial_file': False, 'last': 'unauthorized due to authentication failure.}'}, 'unreachable': {'rc': 1, 'traceback': True, 'partial_file': False, 'last': "Failed to estab |
| A-03 | NEW-UX | Refuted | rc=1 traceback=False last=found: nosuchdb} |
| A-04[empty_file] | NEW-EMPTY | Refuted | rc=1 traceback=False tail=Error: Schema mapping file  /tmp/pytest-of-jicong/pytest-21/test_A04_bad_yaml_clean_error_2/m.yaml is empty.  |
| A-04[missing_field] | H26 | Refuted | rc=1 traceback=False tail=Error: Invalid fields in nodes.Person: NodeTableMapping.__init__() missing 1  required positional argument: 'spanner_table'  |
| A-04[unknown_key] | H26 | Refuted | rc=1 traceback=False tail=Error: Unknown key(s) in nodes.Person: colour  |
| A-06(T1,manual-mapping) | H18 | Refuted | export raised ValueError: invalid literal for int() with base 10: 'not-a-number'; partial files left: [] |
| A-07 |  | Pass | illegal accepted=[] legal rejected=[] |
| A-08 | H04 | Refuted | rejected: Invalid Spanner type 'VARCHAR' on Person.age. |
| A-08(T2) | H04 | Refuted | REJECTED by tool before Spanner: ConfigError: Invalid Spanner type 'VARCHAR' on Ovr.age. |
| A-09b[v44] | NEW-INPUTMAP | Confirmed | {'label_priority_only': 'ConfigError: Schema mapping defines 0 node tables; nothing to export or generate.', 'pk_overrides_only': 'ConfigError: Schema mapping defines 0 node tables; nothing to export or generate.', 'node |
| A-09b[v5] | NEW-INPUTMAP | Confirmed | {'label_priority_only': 'ConfigError: Schema mapping defines 0 node tables; nothing to export or generate.', 'pk_overrides_only': 'ConfigError: Schema mapping defines 0 node tables; nothing to export or generate.', 'node |
| A-10(T3:VLocalDT) |  | Pass | [] |
| B-01[v44] |  | Pass | DiscoveryError: Found 2 node(s) with no labels. All nodes must have at least one label. |
| B-01[v5] |  | Pass | DiscoveryError: Found 2 node(s) with no labels. All nodes must have at least one label. |
| B-02[v44] |  | Pass | DiscoveryError: Ambiguous multi-label nodes detected. Add `label_priority` to schema_mapping.yaml or pass `--label-priority`:   - labels=['A', 'B'] (count=1): multi-label with no constraint or label_priority   - labels=[ |
| B-02[v5] |  | Pass | DiscoveryError: Ambiguous multi-label nodes detected. Add `label_priority` to schema_mapping.yaml or pass `--label-priority`:   - labels=['A', 'B'] (count=1): multi-label with no constraint or label_priority   - labels=[ |
| B-03[v44] |  | Pass | Ambiguous multi-label nodes detected. Add `label_priority` to schema_mapping.yaml or pass `--label-priority`:   - labels=['A', 'B'] (count=1): multiple constrained labels: ['A', 'B'] |
| B-03[v5] |  | Pass | Ambiguous multi-label nodes detected. Add `label_priority` to schema_mapping.yaml or pass `--label-priority`:   - labels=['A', 'B'] (count=1): multiple constrained labels: ['A', 'B'] |
| B-07 |  | Pass | resolved pk=['tenant', 'order_no'] source=node_key synthetic=False |
| B-07(integration) |  | Not testable | NODE_KEY needs Neo4j Enterprise (out of scope, D6) |
| B-10(T2) | H05 | Refuted | {'B10_pk_JSON': 'REJECTED by tool before Spanner: ConfigError: Column Jpk.jk has type JSON, which is not legal as a Spanner PRIMARY KEY.', 'B10_pk_ARRAY': 'REJECTED by tool before Spanner: ConfigError: Column Jpk.jk has  |
| B-10(T3:PkBytes) |  | Pass | [] |
| B-10(T3:PkFloat) |  | Pass | [] |
| B-10(T3:PkTs) |  | Pass | [] |
| B-13 |  | Not testable | Relationship/existence/property-type constraints require Neo4j Enterprise (D6) |
| B-14[v44] | H25 | Refuted | rejected: Neo4j database is empty (0 nodes); cannot generate a Spanner schema. |
| B-14[v5] | H25 | Refuted | rejected: Neo4j database is empty (0 nodes); cannot generate a Spanner schema. |
| B-15(T0) | NEW-MONO | Refuted | _looks_monotonic results (scan-order independent expected): {'descending_ints': True, 'shuffled_dense_ints': True, 'random_uuids': False} |
| BLOCKED:test_A05_chunk_rows_and_workers | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_A06_sample_size_type_drift | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_A10_invalid_timezone_cli | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_B04_label_priority_unknown_and_duplicate[v44] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_B04_label_priority_unknown_and_duplicate[v5] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_B05_B06_partition_invariants[v44] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_B05_B06_partition_invariants[v5] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_B08_uniqueness_with_nulls_falls_back[v44] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_B08_uniqueness_with_nulls_falls_back[v5] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_B09_pk_override_with_duplicates | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_B10_pk_override_illegal_types | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_B11_mixed_type_unique_key_collision | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_B12_constraint_on_secondary_label | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_B15_monotonic_heuristic | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_B16_parallel_edge_detection[v44] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_B16_parallel_edge_detection[v5] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_C01_reserved_keywords_fail_fast_and_rename[v44] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_C01_reserved_keywords_fail_fast_and_rename[v5] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_C03_case_collisions[v44] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_C03_case_collisions[v5] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_C04_unicode_names_collide | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_C05_C09_special_names_preserved[v44] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_C05_C09_special_names_preserved[v5] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_C06_long_names_deterministic[v44] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_C06_long_names_deterministic[v5] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_C10_fixed_column_collisions | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_D03_sparse_property_null_counts | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_D10_int64_override_truncates_in_export | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_E02_sentinel_collision | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_E07_oversize_cell_detection | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_F11b_mapping_independent_of_store_order | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_I01_F11_A09_parity_and_determinism[g5] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_I01_F11_A09_parity_and_determinism[r2] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_I04_neo4j_routing_scheme | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_L01_password_not_logged | NEW-DISCCRASH | Confirmed | CLI `discover --verbose` crashed with UnboundLocalError (fixed_cols_lower) before writing m.yaml; L-01 (password not logged) could not run. Also note: UnboundLocalError is not in the CLI's handled-exception list, so user |
| BLOCKED:test_L02_malicious_names[v44] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| BLOCKED:test_L02_malicious_names[v5] | NEW-DISCCRASH | Confirmed | discover_schema raised UnboundLocalError: cannot access local variable 'fixed_cols_lower' where it is not associated with a value (discovery.py: node-loop references edge-only variable fixed_cols_lower); test could not r |
| C-02 |  | Pass | all statements accepted |
| C-05(T0) | NEW-DIGITNAME | Refuted | property '1st' without rename -> NamingError: Spanner Graph property alias '1st' in node table 'VipCustomer' cannot start with a digit or contain '\'. Add a rename under `nodes.VipCustomer.column_renames` in schema_mappi |
| C-05/C-11/F-10/B-16(GQL) |  | Pass | cypher vs gql: {'reverse_traversal': (40, 40), 'likes_all_triplets': (9672, 9672), 'parallel_follows': (999, 999), 'self_loops': (51, 51), 'two_hop': (10, 10), 'hub_degree': (2000, 2000)} |
| C-07 | H11 | Refuted | all statements accepted |
| C-07(T0) | H11 | Refuted | duplicate FK/index names for two valid 128-char edge tables: [] |
| C-08 | H12 | Refuted | all statements accepted |
| C-08(T0) | H12 | Refuted | longest identifier token in DDL = 128 chars (dst_cccccc...) |
| C-09 | H13 | Confirmed | backtick+backslash: REJECTED by tool before Spanner: NamingError: Spanner Graph LABEL alias 'We`ird\\Label' in node table 'WeirdLabel' cannot start with a digit or contain '\'. Add a rename under `table_renames` in schem |
| C-11 | NEW-LABELCLASH | Refuted | REJECTED by tool before Spanner: NamingError: Relationship type 'KNOWS' shares LABEL 'KNOWS' with a node label but has different properties. Rename the label or relationship type. |
| D-01 |  | Pass | lattice deviations: {} |
| D-02 |  | Pass | 400 random value mixes: coerce_value returns a string or raises a documented ValueError (fail-fast); never another exception |
| D-04(T3:VInt) |  | Pass | [] |
| D-05 | H03 | Refuted | INT64+FLOAT64 -> FLOAT64; with ints > 2^53 -> STRING(MAX); coerce(9007199254740993, FLOAT64) -> ('raised', 'ValueError: Integer 9007199254740993 exceeds 2^53 precision limit for FLOAT64; use override: STRING(MAX)') |
| D-05(T3:TConf) | H03 | Refuted | [] |
| D-06(T3:VFloat) |  | Pass | [] |
| D-07(T3:VFloat) |  | Pass | [] |
| D-08 | H07 | Refuted | results: {'[1.5, nan]': ('ok-rejected', 'ValueError: Cannot serialize ARRAY<FLOAT64> value to RFC8259 JSON (NaN/Infinity is not allowed): Out of range float valu'), '[inf]': ('ok-rejected', 'ValueError: Cannot serialize  |
| D-08(T3)/G-04 | H07 | Refuted | export of [1.5,NaN]/[Infinity,2.0] list values: ('rejected', 'ValueError: Cannot serialize ARRAY<FLOAT64> value to RFC8259 JSON (NaN/Infinity is not allowed): Out of range float values are not JSON compliant: nan') |
| D-09(T3:PkWide) |  | Pass | [] |
| D-10 | H04 | Refuted | override INT64: coerce(3.7) -> ('raised', 'ValueError: Cannot coerce non-integer float 3.7 to INT64 without loss'); coerce('abc') -> ('raised', "ValueError: invalid literal for int() with base 10: 'abc'") |
| D-11 | H04 | Refuted | BOOL coercion results: {'no': ('ok', 'false'), 'N': ('raised', "ValueError: Cannot coerce string 'N' to BOOL"), '0': ('ok', 'false'), 'maybe': ('raised', "ValueError: Cannot coerce string 'maybe' to BOOL"), 'TRUE': ('ok' |
| D-12(T3:VListBool) |  | Pass | [] |
| D-12(T3:VListFloat) |  | Pass | [] |
| D-12(T3:VListStr) |  | Pass | [] |
| D-12(T3:VListTemporal) |  | Pass | [] |
| D-13(T3:VListInt) | H03 | Refuted | [] |
| D-14(T0) | H02 | Refuted | Neo4j DateTime ...00.123456789Z -> CSV '2026-03-15T10:00:00.123456789Z' |
| D-14(T3:VDateTime) | H02 | Refuted | [] |
| D-15 | H22 | Refuted | export raised ValueError: Unsupported or out-of-range Neo4j temporal/hydration value: <neo4j._codec.hydration._common.BrokenHydrationObject object at 0x7fcb6f19e7b0> |
| D-15(T0) | H22 | Observation | Date year 0/10000 handling in coerce_value: {0: ('raised', 'ValueError: Year out of range (1..9999)'), 10000: ('raised', 'ValueError: Year out of range (1..9999)')} |
| D-15(msg) |  | Observation | error identifies table/row: False |
| D-16(T3:VDateTime) | NEW-YEARPAD | Confirmed | VDateTime 'min' = datetime('0001-01-01T00:00:00Z') exported as '1-01-01T00:00:00Z' (new _format_neo4j_datetime_utc uses strftime('%Y'), which does not zero-pad years < 1000 on Linux). Spanner rejected the row (written to |
| D-16(T3:r2,silent) | NEW-SILENTREJECT | Confirmed | R2 runbook exited 0 with 'Load complete!' although Dataflow wrote 1 rejected row to gs://jicong/neo4j-robust/rb-20261119-044800-c2d3/r2/invalid_records/ (VDateTime 'min'). The runbook never inspects invalidOutputPath, so |
| D-17(T3:VDur) |  | Pass | [] |
| D-17(T3:VTime) |  | Pass | [] |
| D-18(T3:VPoint) |  | Pass | [] |
| D-19(T3:VBytes) | NEW-EMPTYBYTES | Refuted | [] |
| E-01(T3:VStr) |  | Pass | [] |
| E-03(T3:VStr) |  | Pass | [] |
| E-03(unescape) | NEW-UNESCAPE | Refuted | load with --emit-unescape succeeded (rc=0); strings after 03_unescape.sql: mismatches={} |
| E-04(T3:VStr) |  | Pass | [] |
| E-06(T3:r3) | NEW-TAB | Confirmed | R3 exported with --delimiter '\t'; runbook now passes columnDelimiter=9 and exits 0 ('Load complete!'), but the template treats '9' as the literal character '9': Spanner holds Company 45/50, Person 1296/2000, Event 39366 |
| E-06/E-08/B-16(T3:r3) |  | Pass | [] |
| E-07(T0) | NEW-SIZE | Refuted | 2.7M-char STRING -> raised (ValueError: STRING value of length 2700000 exceeds Spanner STRING(MAX) limit (2621440 chars)); 10 MiB+1 BYTES -> raised; 2.7M-char ARRAY JSON -> raised; 2.6M 4-byte chars (10.4 MB) -> ok (acce |
| E-07(T3:VStr) |  | Pass | [] |
| E-07(T3:r2) | NEW-HANG | Refuted | R2 nodes job finished normally (rc=0) although Spanner rejected one row: invalidOutputPath=${GCS_PREFIX}/invalid_records/nodes now receives rejected rows instead of the worker-local Finalize hang seen in campaign 1. (R5  |
| E-07(T3:r5) | NEW-HANG | Refuted | value of 2,600,000 4-byte chars (10.4 MB): runbook rc=0 elapsed=1240s, Rj rows in Spanner=2/2, invalid_records objects=0 |
| E-07(T3:r5,silent) | NEW-SILENTREJECT | Refuted | runbook rc=0 ('Load complete!'=True) although only 2/2 Rj rows loaded; rejected rows only visible under gs://jicong/neo4j-robust/rb-20261119-044800-c2d3/r5/invalid_records/ ([]); exporter did not flag the 10.4 MB value ( |
| E-08/C-05(T3:r1) |  | Pass | [] |
| ENV(auth) | NEW-ENV | Observation | gcloud/ADC credentials expired ~07:00 and were renewed by the user at ~07:10; R3 re-load with ';' then completed (rc=0) and its checks were re-run. |
| F-01[B14_nodes_only] | H25 | Refuted | all statements accepted |
| F-01[F03_selfloop_composite] |  | Pass | all statements accepted |
| F-01[G1_baseline] |  | Pass | all statements accepted |
| F-01[G3_special_names] |  | Pass | all statements accepted |
| F-01[G5_topology] |  | Pass | all statements accepted |
| F-01[R2_values_types_pk] |  | Pass | all statements accepted |
| F-02(T3:PkComp) |  | Pass | [] |
| F-02(T3:PkNone) |  | Pass | [] |
| F-04(T1) | H23 | Refuted | discovery of a 1,101-property label: DiscoveryError: Node table 'Wide' has 1101 columns, exceeding Spanner's limit of 1024 columns per table. |
| F-04(T2) |  | Observation | generate_artifacts accepts a hand-built 1,100-column mapping (limit enforced in discovery, see F-04(T1)); Spanner: 01_create_tables.sql: stmt#0 ERROR 400 Table Wide has too many columns; the limit is 1024. 9: Table Wide  |
| F-05 | H08 | Refuted | REJECTED by tool before Spanner: NamingError: Property 'code' has conflicting types across node tables: Person has INT64 vs Company has STRING(MAX). Fix by adding a rename under `nodes.Company.column_renames` or aligning |
| F-06 | H09 | Refuted | all statements accepted |
| F-07 | H09 | Refuted | ARRAY vs INT64: REJECTED by tool before Spanner: NamingError: Edge property 'val' on shared LABEL 'TAGS' has incompatible types (ARRAY<INT64> vs INT64) that cannot be CAST in Spanner Graph DDL. Fix by adding a rename und |
| F-08 | H15 | Refuted | my-graph -> REJECTED by tool before Spanner: NamingError: Invalid Spanner graph identifier 'my-graph' (from 'my-graph') in property graph. Must match [A-Za-z][A-Za-z0-9_]* and be <= 128 chars. Add a rename under `graph_n |
| F-09 | H10 | Confirmed | Cypher MATCH (n:Employee) -> 200; GQL MATCH (n:Employee) -> ERROR 400 Failed to find element label [Employee] in PropertyGraph: RbR3 [at 1:21]\nGRAPH RbR3 MATCH (n:Employee) RETURN COUNT(*) AS c\n                    ^, r |
| F-10/B-10(edges) |  | Pass | [] |
| G-01[r1] |  | Pass | elapsed=1737s jobs=['2026-11-18_21_51_57-1265519816502609427', '2026-11-18_22_00_38-7214887263358959118']  |
| G-01[r2] |  | Pass | elapsed=1814s jobs=['2026-11-18_21_51_59-17598685624480510442', '2026-11-18_22_01_01-12745875584634094112']  |
| G-01[r3] |  | Pass | elapsed=1663s jobs=['2026-11-18_23_13_28-12017390555011089812', '2026-11-18_23_21_45-17666301485141688176']  |
| G-02 |  | Pass | rc=1 elapsed=574s stages=['1. Create Spanner database with Stage 01 DDL (idempotent)', '2. Upload CSV shards and manifests to GCS', '3. Run Dataflow job 1 (Nodes)']; dataflow error: Workflow failed.	 Startup of the worke |
| G-03 |  | Pass | bash -n rc=0 ; shellcheck: shellcheck not installed |
| G-06 | H14 | Refuted | columnDelimiter seen by Dataflow='~'; parsed params=[{'instanceId': 'YOUR_SPANNER_INSTANCE', 'databaseId': 'neo4j_graph', 'importManifest': 'gs://b/run/manifests/nodes_manifest.json', 'columnDelimiter': '~', 'fieldQualif |
| G-07 |  | Pass | rc=0 runs=[['dataflow', 'jobs', 'run', 'neo4j-load-nodes-3491237-21203-1795063686', '--gcs-location=gs://dataflow-templates-asia-southeast1/latest/GCS_Text_to_Cloud_Spanner', '--region=asia-southeast1', '--project=YOUR_P |
| G-08/L-06 |  | Out of scope | Least-privilege SA dropped per D7; default compute SA roles recorded in session.json (very broad: spanner.admin, storage.admin, dataflow.admin, compute.admin, iam.serviceAccountAdmin, ...) |
| G-09(H16-GCS) | H16 | Refuted | upload clears ${GCS_PREFIX}/nodes\|edges\|manifests before copying (cp without delete=False); export passes the exact shard list to the manifest when a summary is available (wildcard-only manifest=True) |
| G-09(H21) | H21 | Refuted | runbook checks for an existing database before `databases create` and offers resume flags (SKIP_DB_CREATE/SKIP_UPLOAD/SKIP_DATAFLOW/SKIP_STAGE_0x): existence check present=True, resume=True |
| G-10(T3:nodes-only) | NEW-NOEDGE | Refuted | nodes-only graph (no relationships): runbook rc=0, Frag rows=2, stages=['1. Create Spanner database with Stage 01 DDL (idempotent)', '2. Upload CSV shards and manifests to GCS', '3. Run Dataflow job 1 (Nodes)', '4. Skip  |
| G-10(nodes-only) | NEW-NOEDGE | Refuted | nodes-only bundle: runbook skips the edges upload/job (unconditional edges upload=False); end-to-end confirmed by G-10(T3:nodes-only) |
| G-11(job-name) | NEW-JOBNAME | Refuted | job name template now neo4j-load-nodes-$$-${RANDOM}-$(date +%s) (includes PID and $RANDOM); 7 runbooks started within 18 s in campaign 2 without collisions |
| H-01 | H01 | Refuted | rc=1 new failures=['sample:PkStr:ps_note:{"sku": "S-005"}'] |
| H-01(golden-vs-verify) | H01 | Refuted | Golden oracle diffs on rb_r2_01 = 1 missing VDateTime row (NEW-YEARPAD); verify detected it via its count check (VDateTime neo4j=9 spanner=8). Lossy-conversion classes from campaign 1 are now caught: H-04 (+1 us TIMESTAM |
| H-02/H-03 |  | Pass | {"delete_node": [1, ["count:VInt", "query:count_node_VInt"]], "delete_edge": [1, ["count:PkStr__REL_A__PkComp", "query:count_edge_REL_A", "query:hop1_PkStr__REL_A__PkComp"]], "insert_edge": [1, ["count:PkInt__REL_E__PkSt |
| H-04 | H02 | Refuted | detected per delta: {'1us': (1, True), '1ms': (1, True)} |
| H-05 | H03 | Refuted | 1-ULP change of VFloat.pi (3.141592653589793 -> 3.1415926535897936): new verify mismatches=[('VFloat', 'f_val')]. (INT>2^53 FLOAT64 sub-case no longer applicable: such columns now widen to STRING(MAX)) |
| H-06 | H19 | Confirmed | Partially fixed. Clean R2 DB: verify no longer crashes (report written) and TIMESTAMP-PK lookups now work (PkTs has no false misses). Still false `missing_in_neo4j`: (a) BYTES PKs - PkBytes 10/10 and PkFloat__REL_D__PkBy |
| H-06(BYTES) | NEW-VERIFYBYTES | Confirmed | verify now compares BYTES without base64-decoding the Spanner client value: R1 Product.payload expected b'abc' vs actual b'YWJj'; R2 VBytes nul_ff expected b'\x00\xff\x00' vs actual b'AP8A'; PkBytes and PkFloat__REL_D__P |
| H-06(FLOAT) | NEW-VERIFYFLOAT | Confirmed | verify _values_equal now requires identical Python types when either side is int: TConf.c_lif ARRAY<FLOAT64> expected [1, 2] (Neo4j ints) vs actual [1.0, 2.0] reported as a mismatch although the values are equal and corr |
| H-06(LABEL) | NEW-LABELRENAME | Confirmed | With table_renames {Order: Orders}, 05_property_graph.sql now declares LABEL `Orders` (node_label_alias = table_renames.get(raw_label)) instead of the original Neo4j label `Order`. README promises original label names in |
| H-07 | H20 | Refuted | 10,000 rows E050000..E059999 corrupted; verify --sample-rows 10000 mismatches in that range per seed: {1: (1, 20), 42: (1, 20)} |
| H-08 |  | Pass | rc=1 query errors=35 first=400 Property graph not found: NoSuchGraph [at 1:7]\nGRAPH NoSuchGraph MATCH (n:`PkBytes`) RETURN COUNT(*) AS cnt\n      ^, request_id = 1.118646617661 |
| H-09 | NEW-UX | Refuted | {"malformed_yaml": {"rc": 1, "traceback": false, "queries": {}}, "bad_cypher_gql": {"rc": 1, "traceback": false, "queries": {"badcy": [false, "{code: Neo.ClientError.Statement.SyntaxError} {message: Invalid input 'MATC': |
| H-10 |  | Pass | keys={'r1': ['counts', 'passed', 'queries', 'samples'], 'r2': ['counts', 'passed', 'queries', 'samples'], 'r3': ['counts', 'passed', 'queries', 'samples'], 'r4': ['counts', 'passed', 'queries', 'samples'], 'r5': ['counts |
| I-03 | H28 | Out of scope | Neo4j 2025.x not tested per D6 (README claims 4.4 + 5.x) |
| K-01 | H24 | Refuted | after `podman pause`, export exited after 120s rc=1 tail='~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File "/usr/local/google/home/jicong/work/neo4j-migration-tool/.venv/lib/python3.13/site-packages/neo4j/_sync/io |
| K-02 | H24 | Refuted | rc=1 traceback=True rows_written=0/300000 artifacts_generated=False |
| K-02(ux) | NEW-UX | Observation | restart error surfaced as: neo4j.exceptions.ServiceUnavailable: Failed to read from defunct connection IPv4Address(('localhost', 7687)) (ResolvedIPv6Address(('::1', 7687, 0, 0))) |
| K-03 | H17 | Refuted | 0-row table: shards=0, manifest references table Gone: False; Dataflow behaviour on an empty glob not tested (GCP fault tests out of scope) |
| K-04 | H27 | Out of scope | Concurrent writes during export: README requires a quiesced DB; dropped per D11 |
| K-05 | H16 | Refuted | re-export into non-empty dir refused: Output directory /tmp/rb/rb-20261119-044800-c2d3/test_K05_stale_shards_on_reexport/export_out already contains nodes, manifests, schema, load_runbook.sh. Use a ; with --overwrite: 2  |
| K-07 |  | Pass | OSError propagated: [Errno 28] No space left on device; artifacts generated=False |
| K-10 | H16 | Refuted | fresh-dir kill leaves complete-looking bundle=False; re-run kill: old runbook/manifests still present=True, rows on disk=300000/300000 (complete first run had 300000), truncated shards=[] |
| L-03 | H15 | Refuted | --gcs-prefix with shell metacharacters rejected at export: NamingError: Invalid --gcs-prefix 'gs://b/$(touch /tmp/pytest-of-jicong/pytest-21/test_L03_gcs_prefix_shell_inje0/sb/rb_pwned)'. Must match gs://<bucket>[/<path> |
| L-04 | H15 | Refuted | rejected: Invalid Spanner graph identifier 'G; DROP TABLE Person' (from 'G; DROP TABLE Person') in property graph. Must match [A-Za-z][A-Za-z0-9_]* and be <= 128 chars. Add a rename under `graph_name` in schema_mapping.y |
| L-05 |  | Pass | 167 objects under gs://jicong/neo4j-robust/rb-20261119-044800-c2d3/; outside=[] |
| T5/J-* |  | Out of scope | Scale tier dropped per D5 |
