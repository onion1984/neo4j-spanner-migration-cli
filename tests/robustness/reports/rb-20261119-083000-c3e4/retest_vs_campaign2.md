# Re-test report

Previous campaign: `rb-20261119-044800-c2d3` · Re-test campaign: `rb-20261119-083000-c3e4`

Verdicts: **Fixed** = 10, **Still open** = 2 · New defects: **0**

## Campaign-1 defects

| DEF | Hypothesis | Sev | Title | Verdict | Re-test tests | Evidence (re-test) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| DEF-001 | NEW-DISCCRASH | P0 | discover crashes on every non-empty graph (UnboundLocalError: fixed_cols_lower, discovery.py:353) | **Fixed** | T1-discovery(all) | All discovery-dependent T1/T6 tests ran (BLOCKED records: 0); T1+T6: 62/62 passed after harness fixes; all 5 T3 graphs discovered. |
| DEF-002 | NEW-TAB | P0 | Tab delimiter breaks the Dataflow load (campaign 2: silent corruption, columnDelimiter=9 treated as the character '9') | **Fixed** | E-06(T3:r3) | R3 exported with --delimiter '\t': runbook rc=0; Spanner counts={'Person': 2000, 'Company': 50, 'Event': 60000, 'Person__KNOWS__Person': 6053, 'Person keys containing TAB': 0} expected={'Person': 2000, 'Company': 50, 'Event': 60000, 'Person__KNOWS__Person': 60 |
| DEF-003 | H10 | P1 | Secondary labels not queryable as GQL labels | **Still open** | F-09 | Cypher MATCH (n:Employee) -> 200; GQL MATCH (n:Employee) -> ERROR 400 Failed to find element label [Employee] in PropertyGraph: RbR3 [at 1:21]\nGRAPH RbR3 MATCH (n:Employee) RETURN COUNT(*) AS c\n                    ^, request_id = 1.3742181418422252134.1.82.1 |
| DEF-004 | H19 | P1 | verify false missing_in_neo4j for widened/TIMESTAMP/BYTES PKs | **Still open** | H-06 | Mostly fixed. Clean R2 DB: verify writes its report; TIMESTAMP-PK (PkTs) and BYTES-PK (PkBytes, PkFloat__REL_D__PkBytes) lookups now pass. Remaining false `missing_in_neo4j`: PkWide wk '1','2','3' (Spanner STRING via user `override: STRING(MAX)`, Neo4j stores  |
| DEF-005 | NEW-INPUTMAP | P1 | Partial --input-mapping files (renames / label_priority / pk_overrides) are rejected by load_mapping validation | **Fixed** | A-09b[v44], A-09b[v5] | {'label_priority_only': 'accepted (then expected reserved-word NamingError for `order`)', 'pk_overrides_only': 'accepted (then expected reserved-word NamingError for `order`)', 'node_column_renames': 'accepted'} |
| DEF-006 | NEW-LABELRENAME | P1 | table_renames now also renames the graph LABEL, losing the original Neo4j label (verify queries fail) | **Fixed** | R1(graph-label) | R1 with table_renames Order->Orders: 05_property_graph.sql declares ['LABEL `Order`']; R1 verify passed=True failed queries=[] |
| DEF-007 | NEW-SILENTREJECT | P1 | Rows rejected by Dataflow are written to invalid_records/ but the runbook still reports success | **Fixed** | E-07(T3:r5,silent), G-12(sandbox) | stub reports 1 object under invalid_records/nodes: runbook rc=1; stderr='ERROR: Dataflow rejected rows written to gs://b/run/invalid_records/nodes:\ngs://b/run/invalid_records/nodes/bad-00000.csv'; 'Load complete!' printed=False |
| DEF-008 | NEW-VERIFYBYTES | P1 | verify reports false mismatches for all BYTES values and BYTES primary keys (no base64 decode) | **Fixed** | R1/R2(verify BYTES) | R1 verify (Product.payload BYTES) passed=True; R2 verify sample failures=['PkTs__REL_B__PkWide', 'PkWide'] (no VBytes/PkBytes/REL_D entries) |
| DEF-009 | NEW-YEARPAD | P1 | TIMESTAMP values with year < 1000 are serialized without zero padding and rejected by Spanner | **Fixed** | D-16(T3:VDateTime) | CSV row min\|0001-01-01T00:00:00Z; VDateTime counts neo4j=9 spanner=9; golden D-16 passed |
| DEF-010 | H13 | P2 | Backtick escaping in graph DDL | **Fixed** | C-09 | backtick+backslash: REJECTED by tool before Spanner: NamingError: Spanner Graph LABEL alias 'We`ird\\Label' in node table 'WeirdLabel' cannot start with a digit or contain '\' or '`'. Add a rename under `table_renames` in schema_mapping.yaml. \|\| backtick onl |
| DEF-011 | NEW-UX | P2 | CLI surfaces operational/validation errors as raw Python tracebacks | **Fixed** | A-02, A-03, A-05, A-10, H-09, K-02(ux) | {"malformed_yaml": {"rc": 1, "traceback": false, "queries": {}}, "bad_cypher_gql": {"rc": 1, "traceback": false, "queries": {"badcy": [false, "{code: Neo.ClientError.Statement.SyntaxError} {message: Invalid input 'MATC': ex"], "badgql": [false, "400 Syntax err |
| DEF-012 | NEW-VERIFYFLOAT | P2 | verify flags equal FLOAT64 values as mismatches when Neo4j stored them as integers | **Fixed** | R2(verify FLOAT64) | R2 verify sample failures=['PkTs__REL_B__PkWide', 'PkWide']: TConf (c_lif ARRAY<FLOAT64> [1,2] vs [1.0,2.0]) no longer flagged; R1 Product.price passed |

## Tests blocked by NEW-DISCCRASH

None.

## New defects found in the re-test

None.
