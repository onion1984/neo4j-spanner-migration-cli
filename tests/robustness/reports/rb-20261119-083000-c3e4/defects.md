# Defect log

Run: `rb-20261119-083000-c3e4` · generated from `findings.jsonl` (latest record per test).

| DEF | Hypothesis | Severity | Title | Tests |
| :--- | :--- | :--- | :--- | :--- |
| DEF-001 | H10 | P1 | Secondary labels not queryable as GQL labels | F-09 |
| DEF-002 | H19 | P2 | verify false missing_in_neo4j for widened/TIMESTAMP/BYTES PKs | H-06 |

### DEF-001 — Secondary labels not queryable as GQL labels

- **Hypothesis:** H10 · **Severity:** P1 · **Status:** Confirmed
- **Tests:** F-09
- **Workaround used / available:** Query `WHERE 'Label' IN UNNEST(n.secondary_labels)` instead of `MATCH (n:Label)`.
- **Evidence:**

  `F-09`

  ```text
  Cypher MATCH (n:Employee) -> 200; GQL MATCH (n:Employee) -> ERROR 400 Failed to find element label [Employee] in PropertyGraph: RbR3 [at 1:21]\nGRAPH RbR3 MATCH (n:Employee) RETURN COUNT(*) AS c\n                    ^, request_id = 1.3742181418422252134.1.82.173.1 [; workaround via secondary_labels -> 200
  ```

### DEF-002 — verify false missing_in_neo4j for widened/TIMESTAMP/BYTES PKs

- **Hypothesis:** H19 · **Severity:** P2 · **Status:** Confirmed
- **Tests:** H-06
- **Workaround used / available:** Interpret verify sample failures on such tables manually.
- **Evidence:**

  `H-06`

  ```text
  Mostly fixed. Clean R2 DB: verify writes its report; TIMESTAMP-PK (PkTs) and BYTES-PK (PkBytes, PkFloat__REL_D__PkBytes) lookups now pass. Remaining false `missing_in_neo4j`: PkWide wk '1','2','3' (Spanner STRING via user `override: STRING(MAX)`, Neo4j stores ints) and the 9 PkTs__REL_B__PkWide edges that reference it. Mixed-type keys are now rejected by discovery (H06), so this only affects explicit overrides.
  ```

