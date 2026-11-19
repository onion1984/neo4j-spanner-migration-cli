# Robustness test summary

Run: `rb-20261119-015500-a1b2`

Records: {'Pass': 75, 'Confirmed': 62, 'Observation': 7, 'Not testable': 2, 'Refuted': 10, 'Out of scope': 4, 'Fail': 1} · Hypotheses: Confirmed=38, Refuted=2, Not testable=0, Out of scope=2, Observation=0

## Hypothesis matrix

| Hypothesis | Description | Status | Tests | Defect |
| :--- | :--- | :--- | :--- | :--- |
| H01 | verify cannot catch coercion bugs (shares coerce_value()) | **Confirmed** | H-01, H-01(golden-vs-verify) | DEF-001 |
| H02 | DateTime ns truncated to µs; verify compares only to ms | **Confirmed** | D-14(T0), D-14(T3:VDateTime), H-04 | DEF-002 |
| H03 | INT64+FLOAT64 widening loses precision > 2^53; verify isclose hides it | **Confirmed** | D-05, D-05(T3:TConf), D-13(T3:VListInt), H-05 | DEF-003 |
| H04 | Type overrides not validated (truncation / silent false / invalid DDL types) | **Confirmed** | A-08, A-08(T2), D-10, D-10(T1), D-11 | DEF-004 |
| H05 | pk_overrides not checked for uniqueness or legal PK type | **Confirmed** | B-09, B-10, B-10(T2) | DEF-005 |
| H06 | Mixed-type unique keys collapse to duplicate STRING PKs | **Confirmed** | B-11 | DEF-007 |
| H07 | NaN/Infinity inside lists -> invalid JSON | **Confirmed** | D-08, D-08(T3)/G-04 | DEF-008 |
| H08 | Same property name, different types across node labels breaks graph DDL | **Confirmed** | F-05 | DEF-006 |
| H09 | Conflicting ARRAY/JSON types on a shared edge label emit an invalid CAST (CAST(NULL AS STRING(MAX)) and INT->STRING are accepted) | **Confirmed** | F-06, F-07 | DEF-009 |
| H10 | Secondary labels not queryable as GQL labels | **Confirmed** | F-09 | DEF-010 |
| H11 | FK/index name truncation collisions | **Confirmed** | C-07, C-07(T0) | DEF-011 |
| H12 | dst_ prefix exceeds 128 chars | **Confirmed** | C-08, C-08(T0) | DEF-023 |
| H13 | Backtick escaping in graph DDL | **Confirmed** | C-09 | DEF-024 |
| H14 | Delimiter '~' breaks Dataflow parameter separator | **Confirmed** | G-06 | DEF-025 |
| H15 | --gcs-prefix / --graph-name injection | **Confirmed** | F-08, L-03, L-04 | DEF-012 |
| H16 | Stale shards loaded (local dir / GCS prefix) | **Confirmed** | G-09(H16-GCS), K-05, K-10 | DEF-013 |
| H17 | 0-row table -> manifest glob matches nothing | **Confirmed** | K-03 | DEF-026 |
| H18 | --sample-size type drift crashes export with partial bundle | **Confirmed** | A-06 | DEF-014 |
| H19 | verify false missing_in_neo4j for widened/TIMESTAMP/BYTES PKs | **Confirmed** | H-06 | DEF-015 |
| H20 | verify sampling limited to first 50k rows | **Confirmed** | H-07 | DEF-027 |
| H21 | Runbook not idempotent / no resume | **Confirmed** | G-09(H21) | DEF-016 |
| H22 | Out-of-range dates crash / corrupt export | **Confirmed** | D-15, D-15(T0) | DEF-017 |
| H23 | Spanner column limit not detected | **Confirmed** | F-04 | DEF-028 |
| H24 | No driver timeout; stalled Neo4j hangs export | **Refuted** | K-01, K-02 | — |
| H25 | Empty DB -> invalid NODE TABLES () | **Confirmed** | B-14[v44], B-14[v5], F-01[B14_nodes_only] | DEF-029 |
| H26 | Unknown/missing YAML keys -> raw TypeError | **Confirmed** | A-04[missing_field], A-04[unknown_key] | DEF-030 |
| H27 | Writes during export -> dangling edges | **Out of scope** | K-04 | — |
| H28 | Neo4j 2025.x calendar versioning | **Out of scope** | I-03 | — |
| H29 | Multi-label partition drops/duplicates rows | **Refuted** | B-05/B-06[v44], B-05/B-06[v5] | — |
| NEW-DET | schema_mapping.yaml not byte-identical across Neo4j versions | **Confirmed** | F-11b, I-01/F-11/A-09[g5], I-01/F-11/A-09[r2] | DEF-031 |
| NEW-DIGITNAME | Original property/label names starting with a digit break CREATE PROPERTY GRAPH | **Confirmed** | C-05(T2)/F-01[G3] | DEF-018 |
| NEW-EMPTY | An empty schema_mapping.yaml exports 0 rows with exit code 0 | **Confirmed** | A-04[empty_file] | DEF-032 |
| NEW-EMPTYBYTES | Empty BYTES values become NULL after load | **Confirmed** | D-19(T3:VBytes) | DEF-033 |
| NEW-HANG | A single rejected row makes the Dataflow load hang (no invalidOutputPath); oversized values not detected | **Confirmed** | D-08(T3:r4), G-01[r2]/E-07(T3) | DEF-019 |
| NEW-JOBNAME | Dataflow job names collide when two loads start in the same second | **Confirmed** | G-11(job-name) | DEF-034 |
| NEW-LABELCLASH | Node label and relationship type with the same name produce conflicting LABEL definitions | **Confirmed** | C-11 | DEF-035 |
| NEW-MONO | Monotonic-PK hotspot warning depends on Neo4j scan order | **Confirmed** | B-15 | DEF-036 |
| NEW-NOEDGE | load_runbook.sh fails for graphs without relationships (missing edges/ directory) | **Confirmed** | G-10(nodes-only) | DEF-020 |
| NEW-SIZE | Values above Spanner limits (STRING 2,621,440 chars / 10 MiB) are not detected before load | **Confirmed** | E-07 | DEF-037 |
| NEW-TAB | Tab delimiter is accepted by export but breaks the Dataflow load | **Confirmed** | E-06(T3:r3) | DEF-021 |
| NEW-UNESCAPE | --emit-unescape generates invalid SQL (03_unescape.sql) and aborts the load | **Confirmed** | E-03(unescape) | DEF-022 |
| NEW-UX | CLI surfaces operational/validation errors as raw Python tracebacks | **Confirmed** | A-02, A-03, A-05, A-10, H-09, K-02(ux) | DEF-038 |

## All test records (latest per test)

| Test | Hyp | Status | Evidence (truncated) |
| :--- | :--- | :--- | :--- |
| A-01 |  | Pass | rc=1 stderr=NEO4J_PASSWORD environment variable (or --password) is required.  |
| A-02 | NEW-UX | Confirmed | {'wrong_password': {'rc': 1, 'traceback': True, 'partial_file': False, 'last': 'neo4j.exceptions.AuthError: {code: Neo.ClientError.Security.Unauthorized} {message: The client is unauthorized due to authentication failure |
| A-03 | NEW-UX | Confirmed | rc=1 traceback=True last=neo4j.exceptions.ClientError: {code: Neo.ClientError.Database.DatabaseNotFound} {message: Graph not found: nosuchdb} |
| A-04[empty_file] | NEW-EMPTY | Confirmed | An empty schema_mapping.yaml is accepted by `export`, which exits 0 and reports 'Export complete: 0 node row(s), 0 edge row(s)'. An empty schema_mapping.yaml is accepted by `export`, which exits 0 and reports 'Export com |
| A-04[missing_field] | H26 | Confirmed | rc=1 traceback=True tail=spanner_export/cli.py", line 58, in _cmd_export     mapping = load_mapping(args.mapping)   File "/usr/local/google/home/jicong/work/neo4j-migration-tool/src/neo4j_spanner_export/config.py", line  |
| A-04[unknown_key] | H26 | Confirmed | rc=1 traceback=True tail=l/src/neo4j_spanner_export/cli.py", line 58, in _cmd_export     mapping = load_mapping(args.mapping)   File "/usr/local/google/home/jicong/work/neo4j-migration-tool/src/neo4j_spanner_export/confi |
| A-05 | NEW-UX | Confirmed | {'chunk0': (1, True, 'ValueError: chunk_rows must be > 0, got 0'), 'workers_neg': (0, False, '/tmp/rb/rb-20261119-015500-a1b2/test_A05_chunk_rows_and_workers/workers_neg'), 'workers64': (0, False, '/tmp/rb/rb-20261119-01 |
| A-06 | H18 | Confirmed | export raised ValueError: invalid literal for int() with base 10: 'not-a-number'; partial files left: ['Dr_part_00000.csv'] |
| A-07 |  | Pass | illegal accepted=[] legal rejected=[] |
| A-08 | H04 | Confirmed | override VARCHAR accepted; DDL contains: ['  age VARCHAR'] |
| A-08(T2) | H04 | Confirmed | invalid override passed through; Spanner: 01_create_tables.sql: stmt#0 ERROR 404 Type not found: VARCHAR. 5: Type not found: VARCHAR. :: CREATE TABLE Ovr (   oid STRING(MAX) NOT NULL,   age VARCHAR ) PRIMARY KEY (oid) 05 |
| A-10 | NEW-UX | Confirmed | rc=1 last=zoneinfo._common.ZoneInfoNotFoundError: 'No time zone found with key Mars/Base' |
| A-10(T3:VLocalDT) |  | Pass | [] |
| B-01[v44] |  | Pass | DiscoveryError: Found 2 node(s) with no labels. All nodes must have at least one label. |
| B-01[v5] |  | Pass | DiscoveryError: Found 2 node(s) with no labels. All nodes must have at least one label. |
| B-02[v44] |  | Pass | DiscoveryError: Ambiguous multi-label nodes detected. Add `label_priority` to schema_mapping.yaml or pass `--label-priority`:   - labels=['A', 'B'] (count=1): multi-label with no constraint or label_priority   - labels=[ |
| B-02[v5] |  | Pass | DiscoveryError: Ambiguous multi-label nodes detected. Add `label_priority` to schema_mapping.yaml or pass `--label-priority`:   - labels=['A', 'B'] (count=1): multi-label with no constraint or label_priority   - labels=[ |
| B-03[v44] |  | Pass | Ambiguous multi-label nodes detected. Add `label_priority` to schema_mapping.yaml or pass `--label-priority`:   - labels=['A', 'B'] (count=1): multiple constrained labels: ['A', 'B'] |
| B-03[v5] |  | Pass | Ambiguous multi-label nodes detected. Add `label_priority` to schema_mapping.yaml or pass `--label-priority`:   - labels=['A', 'B'] (count=1): multiple constrained labels: ['A', 'B'] |
| B-04[v44] |  | Pass | err=None; nodes=['A']; priority kept=['Nope', 'A', 'A'] |
| B-04[v5] |  | Pass | err=None; nodes=['A']; priority kept=['Nope', 'A', 'A'] |
| B-05/B-06[v44] | H29 | Refuted | 60 random graphs; violations=[] |
| B-05/B-06[v5] | H29 | Refuted | 60 random graphs; violations=[] |
| B-07 |  | Pass | resolved pk=['tenant', 'order_no'] source=node_key synthetic=False |
| B-07(integration) |  | Not testable | NODE_KEY needs Neo4j Enterprise (out of scope, D6) |
| B-08[v44] |  | Pass | pk=['_neo4j_id'] source=neo4j_id_fallback warned=True |
| B-08[v5] |  | Pass | pk=['_neo4j_id'] source=neo4j_id_fallback warned=True |
| B-09 | H05 | Confirmed | pk_overrides Ord:[code] accepted; CSV contains duplicate PK values ['X'] -> Dataflow load would hit ALREADY_EXISTS |
| B-10 | H05 | Confirmed | {'tags': ('accepted', 'ARRAY<STRING(MAX)>', ['  tags__json JSON NOT NULL,', ') PRIMARY KEY (tags__json);']), 'loc': ('accepted', 'JSON', ['  loc JSON NOT NULL,', ') PRIMARY KEY (loc);'])} |
| B-10(T2) | H05 | Confirmed | {'B10_pk_JSON': '01_create_tables.sql: stmt#0 ERROR 400 Column Jpk.jk has type JSON, but is part of the primary key. 3: Column Jpk.jk has type JSON, but is part of the primary key. :: CREATE TABLE Jpk (\n  jk JSON NOT NU |
| B-10(T3:PkBytes) |  | Pass | [] |
| B-10(T3:PkFloat) |  | Pass | [] |
| B-10(T3:PkTs) |  | Pass | [] |
| B-11 | H06 | Confirmed | PK type STRING(MAX); CSV keys ['1', '1'] (two distinct Neo4j keys -> one Spanner key) |
| B-12 |  | Observation | Person table pk=['_neo4j_id'] source=neo4j_id_fallback; Employee constraint ignored silently; report mentions Employee: True |
| B-13 |  | Not testable | Relationship/existence/property-type constraints require Neo4j Enterprise (D6) |
| B-14[v44] | H25 | Confirmed | empty DB accepted: 0 tables; 05_property_graph.sql = '-- Stage 05: Create Spanner Property Graph `MigratedGraph`.\nCREATE OR REPLACE PROPERTY GRAPH MigratedGraph\nNODE TABLES (\n\n)\n;\n' |
| B-14[v5] | H25 | Confirmed | empty DB accepted: 0 tables; 05_property_graph.sql = '-- Stage 05: Create Spanner Property Graph `MigratedGraph`.\nCREATE OR REPLACE PROPERTY GRAPH MigratedGraph\nNODE TABLES (\n\n)\n;\n' |
| B-15 | NEW-MONO | Confirmed | sequential INT64 PK 1..50: warn=False; random UUID PK: warn=False (heuristic inspects internal scan order, not key values; store order differs after deletes) |
| B-16[v44] |  | Pass | parallel flags {'N__P__N': True, 'N__Q__N': False, 'N__S__N': True, 'N__T__M': False} |
| B-16[v5] |  | Pass | parallel flags {'N__P__N': True, 'N__Q__N': False, 'N__S__N': True, 'N__T__M': False} |
| C-01[v44] |  | Pass | first=Spanner column identifier 'from' (from 'from') in node table 'Select' is a GoogleSQL reserved keyword. Fix by adding `from: <new_name>` under `nodes.Select.column_renames` in schema_mapping.yaml.; after renames err |
| C-01[v5] |  | Pass | first=Spanner column identifier 'from' (from 'from') in node table 'Select' is a GoogleSQL reserved keyword. Fix by adding `from: <new_name>` under `nodes.Select.column_renames` in schema_mapping.yaml.; after renames err |
| C-02 |  | Pass | all statements accepted |
| C-03[v44] |  | Pass | {'labels': ('NamingError', True), 'props': ('NamingError', True)} |
| C-03[v5] |  | Pass | {'labels': ('NamingError', True), 'props': ('NamingError', True)} |
| C-04 |  | Pass | Case-insensitive table identifier collision in Spanner database: '物' and '人' both map to 'id__'. Fix by adding a rename under `table_renames` in schema_mapping.yaml. |
| C-05(T2)/F-01[G3] | NEW-DIGITNAME | Confirmed | G3 bundle: 05_property_graph.sql rejected by Spanner: "Syntax error on line 6, column 56: Expecting EOF but found an unknown character (\`)" -> position is the alias `1st` in PROPERTIES (id_1st AS `1st`). Spanner DDL doe |
| C-05/C-11/F-10/B-16(GQL) |  | Pass | R1+R3 Cypher vs GQL: vip_label (1,1), reverse_traversal (40,40), likes_all_triplets (9672,9672), parallel_follows (999,999), self_loops (51,51), hub_degree (2000,2000); two_hop Cypher 10 vs GQL 11 is a query-semantics di |
| C-05[v44] |  | Pass | sanitized={'_neo4j_id': 'id__neo4j_id', '1st': 'id_1st', '_under': 'id__under', 'back`tick': 'back_tick', 'dot.prop': 'dot_prop', 'e-mail': 'e_mail', 'first name': 'first_name'}; LABEL line=['LABEL `VIP Customer`'] |
| C-05[v5] |  | Pass | sanitized={'_neo4j_id': 'id__neo4j_id', '1st': 'id_1st', '_under': 'id__under', 'back`tick': 'back_tick', 'dot.prop': 'dot_prop', 'e-mail': 'e_mail', 'first name': 'first_name'}; LABEL line=['LABEL `VIP Customer`'] |
| C-06[v44] |  | Pass | names=[('AAAAAAAAAAAAAAAAAAAA…A_88e685e0', 128), ('AAAAAAAAAAAAAAAAAAAA…A_00931d83', 128), ('ZZZZZZZZZZZZZZZZZZZZ…Z_996e7f1c', 128), ('AAAAAAAAAAAAAAAAAAAA…A_c364aa0d', 128)] |
| C-06[v5] |  | Pass | names=[('AAAAAAAAAAAAAAAAAAAA…A_88e685e0', 128), ('AAAAAAAAAAAAAAAAAAAA…A_00931d83', 128), ('ZZZZZZZZZZZZZZZZZZZZ…Z_996e7f1c', 128), ('AAAAAAAAAAAAAAAAAAAA…A_c364aa0d', 128)] |
| C-07 | H11 | Confirmed | 04_constraints_indexes.sql: stmt#2 ERROR 400 Duplicate name in schema: fk_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA__RELX__BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB. 9: Duplicate name i |
| C-07(T0) | H11 | Confirmed | duplicate FK/index names for two valid 128-char edge tables: ['fk_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA__RELX__BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB', 'idx_AAAAAAAAAAAAAAAAAAAAA |
| C-08 | H12 | Confirmed | 01_create_tables.sql: stmt#2 ERROR 400 Column name not valid: Src__R__Dst.dst_cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc. 3: Column name |
| C-08(T0) | H12 | Confirmed | longest identifier token in DDL = 131 chars (dst_cccccc...) |
| C-09 | H13 | Confirmed | 05_property_graph.sql: stmt#0 ERROR 400 Error analyzing the definition of graph `RbGraph`: Syntax error: Expected \")\" or \",\" but got identifier `ird\\Label` [at 5:15]\n    LABEL `We``ird\\Label`\n              ^ 3: E |
| C-10 |  | Pass | {'edge_id_on_parallel': 'DiscoveryError', 'edge_prop_eq_src_pk': 'DiscoveryError', 'edge_prop_eq_dst_col': 'DiscoveryError', 'secondary_labels_prop': 'NamingError'} |
| C-11 | NEW-LABELCLASH | Confirmed | 05_property_graph.sql: stmt#0 ERROR 400 Error analyzing the definition of graph `RbGraph`: The label \'KNOWS\' is defined with different properties. One definition of the label has 0 property declarations: \'[]\'. Anothe |
| D-01 |  | Pass | lattice deviations: {} |
| D-02 |  | Pass | 400 random value mixes: coerce_value/format_field never raised for inferred types |
| D-03 |  | Pass | null_count=99 type=STRING(MAX) |
| D-04(T3:VInt) |  | Pass | [] |
| D-05 | H03 | Confirmed | INT64+FLOAT64 -> FLOAT64 (conflict=True); coerce(9007199254740993) -> '9007199254740992.0' (int value 9007199254740992); no warning beyond is_conflict flag |
| D-05(T3:TConf) | H03 | Confirmed | [{"table": "TConf", "key": "('r3',)", "column": "c_if", "expected": "9007199254740993", "actual": "9007199254740992.0"}] |
| D-06(T3:VFloat) |  | Pass | [] |
| D-07(T3:VFloat) |  | Pass | [] |
| D-08 | H07 | Confirmed | non-RFC8259 JSON emitted: {'[1.5, nan]': ('INVALID', '[1.5,NaN]', 'non-RFC8259 JSON constant NaN'), '[inf]': ('INVALID', '[Infinity]', 'non-RFC8259 JSON constant Infinity'), "[1, 'a', nan]": ('INVALID', '[1,"a",NaN]', 'n |
| D-08(T3)/G-04 | H07 | Confirmed | R4 ([NaN], [Infinity] list values): rc=1; stages reached=['1. Create Spanner database with Stage 01 DDL', '2. Upload CSV shards and manifests to GCS', '3. Run Dataflow job 1 (Nodes)']; log tail: ING Job 2026-11-18_18_52_ |
| D-08(T3:r4) | NEW-HANG | Confirmed | R4 nodes job 2026-11-18_18_52_50-15698955132928148999: rows with fl_val [1.5,NaN] / [Infinity,2.0] (invalid JSON) were rejected; job then hung >25 min in 'Write failed Spanner records ... Finalize' (LocalFileSystem.match |
| D-09(T3:PkWide) |  | Pass | [] |
| D-10 | H04 | Confirmed | override INT64: coerce(3.7) -> '3' (silent truncation); coerce('abc') -> ValueError: invalid literal for int() with base 10: 'abc' (uncaught at export) |
| D-10(T1) | H04 | Confirmed | override amt: INT64 on [3.7, 10.2] -> CSV ['a,3', 'b,10'] |
| D-11 | H04 | Confirmed | BOOL coercion results: {'no': 'false', 'N': 'false', '0': 'false', 'maybe': 'false', 'TRUE': 'true', 'yes': 'true'}; unknown strings silently -> false: ['maybe', 'N'] |
| D-12(T3:VListBool) |  | Pass | [] |
| D-12(T3:VListFloat) |  | Pass | [] |
| D-12(T3:VListStr) |  | Pass | [] |
| D-12(T3:VListTemporal) |  | Pass | [] |
| D-13(T3:VListInt) | H03 | Refuted | [] |
| D-14(T0) | H02 | Confirmed | Neo4j DateTime ...00.123456789Z -> CSV '2026-03-15T10:00:00.123456Z' |
| D-14(T3:VDateTime) | H02 | Confirmed | [{"table": "VDateTime", "key": "('utc_ns',)", "column": "dt_val", "expected": "('ts', 1773568800, 123456789)", "actual": "('ts', 1773568800, 123456000)"}, {"table": "VDateTime", "key": "('max',)", "column": "dt_val", "ex |
| D-15 | H22 | Confirmed | export succeeded; CSV: ['y0,<neo4j._codec.hydration._common.BrokenHydrationObject object at 0x7f1758578f50>', 'y1,2020-01-01'] |
| D-15(T0) | H22 | Observation | Date year 0/10000 handling in coerce_value: {0: ('raised', 'ValueError: Year out of range (1..9999)'), 10000: ('raised', 'ValueError: Year out of range (1..9999)')} |
| D-16(T3:VDateTime) |  | Pass | [] |
| D-17(T3:VDur) |  | Pass | [] |
| D-17(T3:VTime) |  | Pass | [] |
| D-18(T3:VPoint) |  | Pass | [] |
| D-19(T3:VBytes) | NEW-EMPTYBYTES | Confirmed | Neo4j byte[] of length 0 (case 'empty') is exported as a quoted empty field and arrives in Spanner as NULL (golden expected b''). Non-empty BYTES (incl. \x00\xff and 5 MiB) round-trip exactly. Empty STRING '' is preserve |
| E-01(T3:VStr) |  | Pass | [] |
| E-02 |  | Pass | first error: Literal data value equals null sentinel '__NULL__' in Sn.s (pk=('k1',)). Choose a different --null-string.; alt null-string rows=2 |
| E-03(T3:VStr) |  | Pass | [] |
| E-03(unescape) | NEW-UNESCAPE | Confirmed | With --emit-unescape, runbook stage 6 fails: gcloud spanner databases execute-sql INVALID_ARGUMENT 'Syntax error: Unclosed raw string literal' at ... '__BSLASH__', r'\') ... in 03_unescape.sql (a raw string cannot end wi |
| E-04(T3:VStr) |  | Pass | [] |
| E-06(T3:r3) | NEW-TAB | Confirmed | export --delimiter '\t' is accepted (SerializerConfig maps it to a TAB char) and CSVs are tab-delimited, but load_runbook.sh passes columnDelimiter=\t (2 chars) to GCS_Text_to_Cloud_Spanner. Dataflow job 2026-11-18_18_52 |
| E-06/E-08/B-16(T3:r3) |  | Pass | [] |
| E-07 | NEW-SIZE | Confirmed | 2,700,000-char string exported without warning (rows=1); Spanner STRING(MAX) limit is 2,621,440 chars (10 MiB for BYTES); in T3 such a row was rejected and hung the Dataflow job (NEW-HANG) |
| E-07(T3:VStr) |  | Pass | [] |
| E-08/C-05(T3:r1) |  | Pass | [] |
| F-01[B14_nodes_only] | H25 | Refuted | all statements accepted |
| F-01[F03_selfloop_composite] |  | Pass | all statements accepted |
| F-01[G1_baseline] |  | Pass | all statements accepted |
| F-01[G3_special_names] |  | Fail | setup: stmt#- ERROR 400 Error parsing Spanner DDL statement: CREATE OR REPLACE PROPERTY GRAPH MigratedGraph\nNODE TABLES (\n  VIP_Customer\n    KEY (id__neo4j_id)\n    LABEL `VIP Customer`\n    PROPERTIES (id__neo4j_id A |
| F-01[G5_topology] |  | Pass | all statements accepted |
| F-01[R2_values_types_pk] |  | Pass | all statements accepted |
| F-02(T3:PkComp) |  | Pass | [] |
| F-02(T3:PkNone) |  | Pass | [] |
| F-04 | H23 | Confirmed | tool emitted a 1,100-column table without warning; Spanner: 01_create_tables.sql: stmt#0 ERROR 400 Table Wide has too many columns; the limit is 1024. 9: Table Wide has too many columns; the limit is 1024. :: CREATE TABL |
| F-05 | H08 | Confirmed | 05_property_graph.sql: stmt#0 ERROR 400 Error analyzing the definition of graph `RbGraph`: The property declaration of \'code\' has type conflicts. There is an existing declaration of type STRING. There is a conflicting  |
| F-06 | H09 | Refuted | all statements accepted |
| F-07 | H09 | Confirmed | ARRAY vs INT64: 05_property_graph.sql: stmt#0 ERROR 400 Error analyzing the definition of graph `RbGraph`: Invalid cast from ARRAY<INT64> to STRING [at 19:14]\n        CAST(val AS STRING(MAX)) AS val),\n             ^ 3: |
| F-08 | H15 | Confirmed | --graph-name accepted by tool; Spanner: my-graph -> 05_property_graph.sql: stmt#0 ERROR 400 Error analyzing the definition of graph `my`: Syntax error: Expected \".\" or keyword NODE but got \"-\" [at 1:36]\nCREATE OR RE |
| F-09 | H10 | Confirmed | Cypher MATCH (n:Employee) -> 200; GQL MATCH (n:Employee) -> ERROR 400 Failed to find element label [Employee] in PropertyGraph: RbR3 [at 1:21]\nGRAPH RbR3 MATCH (n:Employee) RETURN COUNT(*) AS c\n                    ^, r |
| F-10/B-10(edges) |  | Pass | [] |
| F-10/GQL-semantics |  | Observation | Custom --queries-file pairs must use `MATCH TRAIL` (or explicit edge-distinctness) in GQL to mirror Cypher's relationship-uniqueness semantics; the tool's built-in equivalence queries are single-hop and unaffected. Consi |
| F-11b | NEW-DET | Confirmed | mapping differs only by creation order; diff lines: ['-    monotonic_pk_warning: true', '+    monotonic_pk_warning: false', '+          INT64: 20', '-          INT64: 20'] |
| G-01[r1] |  | Pass | elapsed=1611s jobs=['2026-11-18_18_15_16-9473484272211380108', '2026-11-18_18_23_35-15318619655953185524']  |
| G-01[r2] |  | Pass | elapsed=1402s jobs=['2026-11-18_19_04_46-3700330028325993688', '2026-11-18_19_13_01-10080693753168482412']  |
| G-01[r2]/E-07(T3) | NEW-HANG | Confirmed | R2 nodes Dataflow job 2026-11-18_18_15_03-12830543361029124285 loaded 23/24 VStr rows; the row with a 10,380,918-char string (STRING(MAX) limit is 2,621,440 characters) was rejected by Spanner. The runbook does not pass  |
| G-01[r3] |  | Pass | elapsed=1842s jobs=['2026-11-18_19_23_54-6406754660791356303', '2026-11-18_19_32_11-13425723967970167981']  |
| G-02 |  | Pass | rc=1 elapsed=535s stages=['1. Create Spanner database with Stage 01 DDL', '2. Upload CSV shards and manifests to GCS', '3. Run Dataflow job 1 (Nodes)']; dataflow error: Workflow failed.	 Startup of the worker pool in asi |
| G-03 |  | Pass | bash -n rc=0 ; shellcheck: shellcheck not installed |
| G-06 | H14 | Confirmed | columnDelimiter seen by Dataflow=''; parsed params=[{'instanceId': 'YOUR_SPANNER_INSTANCE', 'databaseId': 'neo4j_graph', 'importManifest': 'gs://b/run/manifests/nodes_manifest.json', 'columnDelimiter': '', '': '', 'field |
| G-07 |  | Pass | rc=0 runs=[['dataflow', 'jobs', 'run', 'neo4j-load-nodes-1795053525', '--gcs-location=gs://dataflow-templates-asia-southeast1/latest/GCS_Text_to_Cloud_Spanner', '--region=asia-southeast1', '--project=YOUR_PROJECT_ID', '- |
| G-08/L-06 |  | Out of scope | Least-privilege SA dropped per D7; default compute SA roles recorded in session.json (very broad: spanner.admin, storage.admin, dataflow.admin, compute.admin, iam.serviceAccountAdmin, ...) |
| G-09(H16-GCS) | H16 | Confirmed | upload uses `gcloud storage cp --recursive` without clearing the prefix (True) and the manifest uses a wildcard `<table>_part_*.csv` (True); stale shards from an earlier, larger export under the same GCS_PREFIX are loade |
| G-09(H21) | H21 | Confirmed | runbook runs `gcloud spanner databases create` unconditionally under `set -euo pipefail` (no existence check: True); resume/skip-stage support: False. A re-run after success fails at stage 1; a failure after stage 3 cann |
| G-10(nodes-only) | NEW-NOEDGE | Confirmed | exporter writes no edges/ dir when there are no relationships, but the runbook always runs `gcloud storage cp --recursive .../edges` under set -e (True) and always launches the edges Dataflow job (True). Observed in T3:  |
| G-11(job-name) | NEW-JOBNAME | Confirmed | Dataflow job names are `neo4j-load-{nodes,edges}-$(date +%s)` (not unique per database/run): two runbooks started within the same second collide. Observed: ['ERROR: (gcloud.dataflow.jobs.run) ALREADY_EXISTS: (81d5770538f |
| H-01 | H01 | Refuted | rc=1 new failures=['sample:PkStr:ps_note:{"sku": "S-005"}'] |
| H-01(golden-vs-verify) | H01 | Confirmed | Same loaded DB rb_r2_01: independent golden oracle found 4 value diffs [('VBytes', "('empty',)", 'by_val'), ('VDateTime', "('utc_ns',)", 'dt_val'), ('VDateTime', "('max',)", 'dt_val'), ('TConf', "('r3',)", 'c_if')]; veri |
| H-02/H-03 |  | Pass | {"delete_node": [1, ["count:VInt", "query:count_node_VInt"]], "delete_edge": [1, ["count:PkStr__REL_A__PkComp", "query:count_edge_REL_A", "query:hop1_PkStr__REL_A__PkComp"]], "insert_edge": [1, ["count:PkInt__REL_E__PkSt |
| H-04 | H02 | Confirmed | detected per delta: {'1us': (1, False), '1ms': (1, True)} |
| H-05 | H03 | Confirmed | 1-ULP FLOAT64 change detected=False; INT>2^53 in FLOAT64 col changed by 2 detected=False |
| H-06 | H19 | Confirmed | Clean R2 DB (all values loaded) -> `verify` exits 1 WITHOUT writing a report: (1) TIMESTAMP PK (PkTs.ts): Spanner DatetimeWithNanoseconds is passed as a Neo4j query parameter -> ValueError: Values of type DatetimeWithNan |
| H-06(all) |  | Observation | baseline verify rc: {'r3': 0}; failures: {"r3": []} |
| H-07 | H20 | Confirmed | row E059999 (last PK range of 60k-row table) corrupted; detected per seed: {1: (0, False), 42: (0, False), 7: (0, False)} (verify reads only first max(n*5,50000) rows) |
| H-08 |  | Pass | rc=1 query errors=29 first=400 Property graph not found: NoSuchGraph [at 1:7]\nGRAPH NoSuchGraph MATCH (n:`PkComp`) RETURN COUNT(*) AS cnt\n      ^, request_id = 1.3919458997340 |
| H-09 | NEW-UX | Confirmed | {"malformed_yaml": {"rc": 1, "traceback": true, "queries": {}}, "bad_cypher_gql": {"rc": 1, "traceback": false, "queries": {"badcy": [false, "{code: Neo.ClientError.Statement.SyntaxError} {message: Invalid input 'MATC':  |
| H-10 |  | Pass | keys={'r3': ['counts', 'passed', 'queries', 'samples']} password_in_report=False |
| I-01/F-11/A-09[g5] | NEW-DET | Refuted | determinism(ddl,mapping)={'v5': (True, True), 'v44': (True, True)} parity ddl=True mapping=True csv tables differing=[] (mapping diff between 4.4 and 5.x is only the key order of `observed:` type counts) |
| I-01/F-11/A-09[r2] | NEW-DET | Refuted | determinism(ddl,mapping)={'v5': (True, True), 'v44': (True, True)} parity ddl=True mapping=True csv tables differing=[] (mapping diff between 4.4 and 5.x is only the key order of `observed:` type counts) |
| I-03 | H28 | Out of scope | Neo4j 2025.x not tested per D6 (README claims 4.4 + 5.x) |
| I-04 |  | Pass | {'v5': ['R'], 'v44': ['R']} |
| K-01 | H24 | Refuted | after `podman pause`, export exited after 121s rc=1 tail='~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File "/usr/local/google/home/jicong/work/neo4j-migration-tool/.venv/lib/python3.13/site-packages/neo4j/_sync/io |
| K-02 | H24 | Refuted | rc=1 traceback=True rows_written=85000/300000 artifacts_generated=False |
| K-02(ux) | NEW-UX | Observation | restart error surfaced as: neo4j.exceptions.ServiceUnavailable: Failed to read from defunct connection IPv4Address(('localhost', 7687)) (ResolvedIPv6Address(('::1', 7687, 0, 0))) |
| K-03 | H17 | Confirmed | 0-row table: no error, shards=0, manifest still lists 'Gone_part_*.csv' (True); Dataflow behaviour on an empty glob not tested (GCP fault tests out of scope) |
| K-04 | H27 | Out of scope | Concurrent writes during export: README requires a quiesced DB; dropped per D11 |
| K-05 | H16 | Confirmed | second export reported 2 rows but 6 shards / 6 rows match the manifest glob (['St_part_00000.csv', 'St_part_00001.csv', 'St_part_00002.csv', 'St_part_00003.csv', 'St_part_00004.csv', 'St_part_00005.csv']) |
| K-07 |  | Pass | OSError propagated: [Errno 28] No space left on device; artifacts generated=False |
| K-10 | H16 | Confirmed | fresh-dir kill leaves complete-looking bundle=False; re-run kill: old runbook/manifests still present=True, rows on disk=54000/300000 (complete first run had 300000), truncated shards=[] |
| L-01 |  | Pass | rc=0; password present in output/artifacts: False |
| L-01(ps) |  | Observation | --password is visible in the process list / shell history; README recommends NEO4J_PASSWORD env var |
| L-02[v44] |  | Pass | tables=['Safe', 'a___DROP_TABLE_x____'] edges=['a___DROP_TABLE_x______r__DELETE__Safe'] |
| L-02[v5] |  | Pass | tables=['Safe', 'a___DROP_TABLE_x____'] edges=['a___DROP_TABLE_x______r__DELETE__Safe'] |
| L-03 | H15 | Confirmed | --gcs-prefix 'gs://b/$(touch …)' accepted by export; running load_runbook.sh executed it: marker exists=True; runbook line: ['GCS_PREFIX="${GCS_PREFIX:-gs://b/$(touch /tmp/pytest-of-jicong/pytest-10/test_L03_gcs_prefix_s |
| L-04 | H15 | Confirmed | --graph-name accepted; 05_property_graph.sql head: 'CREATE OR REPLACE PROPERTY GRAPH G; DROP TABLE Person' |
| L-05 |  | Pass | 152 objects under gs://jicong/neo4j-robust/rb-20261119-015500-a1b2/; outside=[] |
| T4-rerun(setup) |  | Observation | T4 re-run baseline verify rc=1 with workaround mapping (PkTs, PkBytes and their edges removed); baseline failures=['sample:PkNone:missing_in_neo4j:{"id__neo4j_id": -1369094286720630784}', 'sample:PkNone:missing_in_neo4j: |
| T5/J-* |  | Out of scope | Scale tier dropped per D5 |
